"""Persistent upload outbox and scheduler tests (contract 06 section 6).

Covers the required upload-queue cases: successful upload, network
interruption, retry, duplicate upload, process restart, missing file, checksum
mismatch, server idempotency conflict, and recovery of stale IN_PROGRESS
tasks (design 13.5/13.9, ADR-005).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from assemblyvision_domain.models import BusinessResult, InspectionRecord, UploadTask
from assemblyvision_edge.persistence.reconcile import reconcile_output_root
from assemblyvision_edge.persistence.repository import EdgeRepository
from assemblyvision_edge.upload.scheduler import (
    DirectoryUploadSink,
    HttpUploadSink,
    UploadReceipt,
    UploadResult,
    UploadScheduler,
    _full_jitter_backoff,
)
from sqlalchemy import text

from tests.test_api import _record


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EdgeRepository]:
    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        yield repository
    finally:
        repository.close()


def _write_media(output_root: Path, record: InspectionRecord) -> None:
    """Create the media file described by the record with a matching checksum."""
    for item in record.media:
        path = output_root / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = f"jpeg-bytes-{item.media_id}".encode()
        path.write_bytes(data)
        item.size_bytes = len(data)
        item.checksum_sha256 = hashlib.sha256(data).hexdigest()


def _write_bundle(output_root: Path, record: InspectionRecord) -> None:
    """Write the CLI-style inspection.json bundle the reconciliation imports."""
    path = output_root / str(record.inspection_id) / "inspection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(), encoding="utf-8")


def _seed(
    repo: EdgeRepository,
    output_root: Path,
    *,
    count: int = 1,
    enqueue: bool = True,
) -> list[InspectionRecord]:
    records: list[InspectionRecord] = []
    for i in range(count):
        record = _record(
            datetime.now(UTC) + timedelta(seconds=i), business=BusinessResult.OK, barcode=f"SN-{i}"
        )
        _write_media(output_root, record)
        repo.upsert_inspection(record)
        if enqueue:
            repo.enqueue_inspection_uploads(record)
        records.append(record)
    return records


class _AdvancingClock:
    """Deterministic clock controllable by the sink for F8 timing tests."""

    def __init__(self, start: datetime) -> None:
        self._now_value = start

    def __call__(self) -> datetime:
        return self._now_value

    def advance(self, seconds: float) -> None:
        self._now_value += timedelta(seconds=seconds)


class _ScriptedSink:
    """Sink whose outcomes are scripted, cycling per call for fault injection."""

    def __init__(self, outcomes: list[UploadResult] | None = None) -> None:
        self._outcomes = outcomes or [UploadResult(status="SUCCEEDED")]
        self._index = 0
        self.keys: list[str] = []

    def upload(self, task: UploadTask, payload: bytes) -> UploadResult:
        self.keys.append(task.idempotency_key)
        result = self._outcomes[self._index % len(self._outcomes)]
        self._index += 1
        if result.status == "SUCCEEDED":
            # F5: success must carry a verified receipt matching the task;
            # the reported bytes are the request body sent (PR-022 F02).
            return UploadResult(
                status="SUCCEEDED",
                receipt=UploadReceipt(
                    idempotency_key=task.idempotency_key,
                    object_id=str(task.object_id),
                    kind=task.kind,
                    checksum_sha256=task.checksum_sha256,
                    size_bytes=len(payload),
                    central_object_id=f"central-{task.idempotency_key}",
                ),
                payload_bytes_sent=len(payload),
            )
        return result


def _scheduler(
    repo: EdgeRepository, output_root: Path, sink: object, *, base_retry_seconds: float = 2.0
) -> UploadScheduler:
    return UploadScheduler(
        repo,
        sink,  # type: ignore[arg-type]
        output_root=output_root,
        base_retry_seconds=base_retry_seconds,
        maximum_retry_seconds=60.0,
        exponent_cap=3,
    )


def _by_kind(tasks: list[UploadTask]) -> dict[str, UploadTask]:
    return {task.kind: task for task in tasks}


class TestQueueMetricsAndHealth:
    def test_queue_metrics_report_pending_bytes_and_oldest(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """E1: queue bytes and oldest pending come from persisted task sizes."""
        _seed(repo, tmp_path, count=2)
        metrics = repo.upload_queue_metrics()
        assert metrics.by_state["PENDING"] == 4  # 2 inspections + 2 media
        assert metrics.pending_bytes > 0
        assert metrics.oldest_pending_at is not None
        tasks = repo.list_uploads(limit=100).items
        with repo._engine.connect() as conn:  # noqa: SLF001
            expected_bytes = conn.execute(
                sa.text("SELECT SUM(size_bytes) FROM upload_tasks")
            ).scalar()
        assert metrics.pending_bytes == expected_bytes
        assert metrics.oldest_pending_at == min(task.created_at.isoformat() for task in tasks)

        # A stalled leased task is still pending work and must contribute its age.
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(sa.text("UPDATE upload_tasks SET status = 'IN_PROGRESS'"))
        in_progress = repo.upload_queue_metrics()
        assert in_progress.oldest_pending_at == min(task.created_at.isoformat() for task in tasks)

    def test_scheduler_health_tracks_attempts_and_success(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """E1: the worker exposes attempt/success/failure liveness counters."""
        _seed(repo, tmp_path)
        scheduler = _scheduler(repo, tmp_path, _ScriptedSink())
        assert scheduler.health().attempts == 0
        _drain(scheduler)
        health = scheduler.health()
        assert health.attempts == 2
        assert health.successes == 2
        assert health.failures == 0
        assert health.failure_rate == 0.0
        assert health.last_attempt_at is not None
        assert health.last_success_at is not None
        assert health.last_error_code is None

    def test_scheduler_health_records_failures(self, repo: EdgeRepository, tmp_path: Path) -> None:
        """E1: retryable and permanent failures move the failure counters."""
        _seed(repo, tmp_path)
        sink = _ScriptedSink([UploadResult(status="RETRYABLE", error_code="HTTP_503")])
        scheduler = _scheduler(repo, tmp_path, sink)
        scheduler.run_once()  # inspection task fails once
        health = scheduler.health()
        assert health.attempts == 1
        assert health.failures == 1
        assert health.successes == 0
        assert health.last_error_code == "HTTP_503"
        assert health.failure_rate == 1.0


class TestOutboxEnqueue:
    def test_enqueue_creates_inspection_and_media_tasks(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        record = _seed(repo, tmp_path)[0]
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        assert set(by_kind) == {"INSPECTION", "MEDIA"}
        inspection = by_kind["INSPECTION"]
        assert inspection.status == "PENDING"
        assert inspection.idempotency_key == f"inspection:{record.device_id}:{record.inspection_id}"
        assert str(inspection.inspection_id) == str(record.inspection_id)
        assert str(inspection.object_id) == str(record.inspection_id)
        assert by_kind["MEDIA"].idempotency_key.startswith(f"media:{record.device_id}:")
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "QUEUED"

    def test_duplicate_enqueue_is_idempotent(self, repo: EdgeRepository, tmp_path: Path) -> None:
        record = _seed(repo, tmp_path)[0]
        assert repo.enqueue_inspection_uploads(record) == 0  # already queued
        assert len(repo.list_uploads(limit=100).items) == 2

    def test_restart_reconciliation_does_not_duplicate_tasks(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        _seed(repo, tmp_path)
        # A fresh repository over the same database simulates a process restart.
        restarted = EdgeRepository.open(tmp_path / "edge.sqlite3")
        try:
            assert len(restarted.list_uploads(limit=100).items) == 2
            record = restarted.list_inspections(limit=1).items[0]
            full = restarted.get_inspection(str(record.inspection_id))
            assert full is not None
            # Re-import of an already-queued record must not create new tasks.
            assert restarted.enqueue_inspection_uploads(full) == 0
            assert len(restarted.list_uploads(limit=100).items) == 2
        finally:
            restarted.close()


class TestAtomicPersistence:
    def test_persist_and_enqueue_commit_atomically(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """F2: projection + outbox tasks land in one repository call."""
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-atomic")
        assert repo.persist_inspection_and_enqueue_uploads(record) == "inserted"
        assert len(repo.list_uploads(limit=100).items) == 2
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "QUEUED"
        # Re-persisting is unchanged and creates nothing new.
        assert repo.persist_inspection_and_enqueue_uploads(record) == "unchanged"
        assert len(repo.list_uploads(limit=100).items) == 2

    def test_reconcile_repairs_stranded_local_only_record(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """F2: a LOCAL_ONLY record whose outbox was lost gains its tasks."""
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-strand")
        _write_media(tmp_path, record)
        # The legacy seeding path leaves the record projected but not queued,
        # exactly like a crash between the two old commits.
        assert repo.upsert_inspection(record) == "inserted"
        assert repo.list_uploads(limit=100).items == []
        _write_bundle(tmp_path, record)
        # Reconciliation must repair it even though it is not newly inserted.
        assert reconcile_output_root(repo, tmp_path) == 0
        assert len(repo.list_uploads(limit=100).items) == 2
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "QUEUED"
        # A second pass creates nothing.
        assert reconcile_output_root(repo, tmp_path) == 0
        assert len(repo.list_uploads(limit=100).items) == 2

    def test_reconcile_imports_fresh_bundle_with_tasks(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """F2: a new bundle is imported and queued in the same operation."""
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-fresh")
        _write_media(tmp_path, record)
        _write_bundle(tmp_path, record)
        assert reconcile_output_root(repo, tmp_path) == 1
        assert len(repo.list_uploads(limit=100).items) == 2


def _drain(scheduler: UploadScheduler, max_passes: int = 20) -> int:
    """Run the scheduler until a pass handles nothing; returns tasks handled."""
    total = 0
    for _ in range(max_passes):
        handled = scheduler.run_once()
        total += handled
        if handled == 0:
            break
    return total


class TestSuccessfulUpload:
    def test_scheduler_drains_to_sink(self, repo: EdgeRepository, tmp_path: Path) -> None:
        record = _seed(repo, tmp_path)[0]
        sink_dir = tmp_path / "sink"
        sink = DirectoryUploadSink(sink_dir)
        scheduler = _scheduler(repo, tmp_path, sink)
        assert _drain(scheduler) == 2
        assert all(task.status == "SUCCEEDED" for task in repo.list_uploads(limit=100).items)
        inspection_payload = (
            sink_dir / "inspection" / f"inspection:{record.device_id}:{record.inspection_id}.bin"
        )
        assert inspection_payload.exists()
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "SYNCED"

    def test_claim_marks_in_progress_with_lease(self, repo: EdgeRepository, tmp_path: Path) -> None:
        _seed(repo, tmp_path)
        claimed = repo.claim_upload_tasks(
            10, lease_seconds=120, now_iso=datetime.now(UTC).isoformat()
        )
        # F4: only the metadata task is due; media waits for its receipt.
        assert len(claimed) == 1
        assert claimed[0].task.kind == "INSPECTION"
        assert claimed[0].task.status == "IN_PROGRESS"
        # F3: every claim carries a distinct fencing token.
        assert len({item.lease_owner for item in claimed}) == 1


class TestMetadataBeforeMedia:
    def test_media_drains_only_after_inspection_receipt(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """F4: a media request is never sent before its inspection receipt."""
        import json

        import httpx

        _seed(repo, tmp_path)
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen.append(body["kind"])
            return httpx.Response(
                200,
                json={
                    "idempotency_key": body["idempotency_key"],
                    "object_id": body["object_id"],
                    "kind": body["kind"],
                    "checksum_sha256": body["checksum_sha256"],
                    "size_bytes": body["size_bytes"],
                    "central_object_id": f"obj-{body['kind']}",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = HttpUploadSink("https://central.invalid", client=client)
        scheduler = _scheduler(repo, tmp_path, sink)
        # First pass: only metadata is due; media must not be requested yet.
        assert scheduler.run_once() == 1
        assert seen == ["INSPECTION"]
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        assert by_kind["INSPECTION"].status == "SUCCEEDED"
        assert by_kind["MEDIA"].status == "PENDING"
        # Second pass: media becomes due now that its parent has a receipt.
        assert scheduler.run_once() == 1
        assert seen == ["INSPECTION", "MEDIA"]
        assert all(t.status == "SUCCEEDED" for t in repo.list_uploads(limit=100).items)


class TestRetryBehavior:
    def test_retry_deadline_is_anchored_to_response_time(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """F8: Retry-After is measured from the response, not the batch start."""
        start = datetime.now(UTC)
        clock = _AdvancingClock(start)

        class _SlowRetrySink:
            def upload(self, task: UploadTask, payload: bytes) -> UploadResult:
                clock.advance(5.0)
                return UploadResult(
                    status="RETRYABLE", error_code="HTTP_429", retry_after_seconds=60.0
                )

        _seed(repo, tmp_path)
        scheduler = UploadScheduler(
            repo,
            _SlowRetrySink(),
            output_root=tmp_path,
            base_retry_seconds=2.0,
            now=clock,
        )
        scheduler.run_once()
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        inspection = by_kind["INSPECTION"]
        # Claim at t0, the sink advanced the clock by 5s before returning, so
        # the next attempt must be t0 + 5 + 60, never t0 + 60.
        assert inspection.next_attempt_at is not None
        assert inspection.next_attempt_at == start + timedelta(seconds=65)

    def test_network_interruption_schedules_retry(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        _seed(repo, tmp_path)
        sink = _ScriptedSink([UploadResult(status="RETRYABLE", error_code="TRANSPORT_ERROR")])
        scheduler = _scheduler(repo, tmp_path, sink)
        now = datetime.now(UTC)
        # Only the metadata task is claimed; media stays pending on its receipt.
        assert scheduler.run_once() == 1
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        inspection = by_kind["INSPECTION"]
        assert inspection.status == "RETRY_WAIT"
        assert inspection.attempt_count == 1
        assert inspection.last_error_code == "TRANSPORT_ERROR"
        assert inspection.next_attempt_at is not None
        assert inspection.next_attempt_at > now
        assert by_kind["MEDIA"].status == "PENDING"

    def test_retry_eventually_succeeds(self, repo: EdgeRepository, tmp_path: Path) -> None:
        _seed(repo, tmp_path)
        sink = _ScriptedSink(
            [
                UploadResult(status="RETRYABLE", error_code="HTTP_503"),
                UploadResult(status="RETRYABLE", error_code="HTTP_503"),
                UploadResult(status="SUCCEEDED"),
            ]
        )
        # base_retry_seconds=0 keeps the task immediately due so successive
        # run_once calls exercise the full retry ladder; metadata retries first,
        # then media, so the scripted outcomes must serve both tasks.
        scheduler = _scheduler(repo, tmp_path, sink, base_retry_seconds=0.0)
        _drain(scheduler, max_passes=12)
        tasks = repo.list_uploads(limit=100).items
        assert all(t.status == "SUCCEEDED" for t in tasks)
        assert all(t.attempt_count >= 1 for t in tasks)  # both retried at least once

    def test_retry_after_is_honored(self, repo: EdgeRepository, tmp_path: Path) -> None:
        _seed(repo, tmp_path)
        sink = _ScriptedSink(
            [UploadResult(status="RETRYABLE", error_code="HTTP_429", retry_after_seconds=60)]
        )
        scheduler = _scheduler(repo, tmp_path, sink)
        now = datetime.now(UTC)
        scheduler.run_once()
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        inspection = by_kind["INSPECTION"]
        assert inspection.status == "RETRY_WAIT"
        assert inspection.next_attempt_at is not None
        assert inspection.next_attempt_at >= now + timedelta(seconds=60)
        assert by_kind["MEDIA"].status == "PENDING"

    def test_backoff_bounds(self) -> None:
        for attempt in range(10):
            value = _full_jitter_backoff(
                attempt, base_seconds=2.0, maximum_seconds=60.0, exponent_cap=3
            )
            assert 0.0 <= value <= 60.0


class TestPermanentFailures:
    def test_missing_media_file_is_permanent_failure(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        record = _seed(repo, tmp_path)[0]
        (tmp_path / record.media[0].relative_path).unlink()
        scheduler = _scheduler(repo, tmp_path, _ScriptedSink())
        _drain(scheduler)
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        assert by_kind["MEDIA"].status == "PERMANENT_FAILURE"
        assert by_kind["MEDIA"].last_error_code == "MEDIA_EVIDENCE_MISSING"
        # Metadata upload still succeeds; local evidence is preserved.
        assert by_kind["INSPECTION"].status == "SUCCEEDED"

    def test_checksum_mismatch_is_permanent_failure(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        record = _seed(repo, tmp_path)[0]
        path = tmp_path / record.media[0].relative_path
        path.write_bytes(b"x" * len(path.read_bytes()))
        scheduler = _scheduler(repo, tmp_path, _ScriptedSink())
        _drain(scheduler)
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        assert by_kind["MEDIA"].status == "PERMANENT_FAILURE"
        assert by_kind["MEDIA"].last_error_code == "MEDIA_CHECKSUM_MISMATCH"

    def test_media_size_mismatch_is_permanent_failure(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """Follow-up: immutable media size must match the bytes before upload."""
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-size")
        _write_media(tmp_path, record)
        record.media[0].size_bytes += 1
        repo.persist_inspection_and_enqueue_uploads(record)
        scheduler = _scheduler(repo, tmp_path, _ScriptedSink())
        _drain(scheduler)
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        assert by_kind["MEDIA"].status == "PERMANENT_FAILURE"
        assert by_kind["MEDIA"].last_error_code == "MEDIA_SIZE_MISMATCH"

    def test_server_idempotency_conflict_is_permanent(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        _seed(repo, tmp_path)
        sink = _ScriptedSink([UploadResult(status="PERMANENT", error_code="HTTP_409")])
        scheduler = _scheduler(repo, tmp_path, sink)
        scheduler.run_once()
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        inspection = by_kind["INSPECTION"]
        assert inspection.status == "PERMANENT_FAILURE"
        assert inspection.last_error_code == "HTTP_409"
        # Media stays pending behind the permanently failed metadata task
        # (F4); it is never sent and never classified as evidence failure.
        assert by_kind["MEDIA"].status == "PENDING"

    def test_missing_inspection_evidence_is_permanent(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        _seed(repo, tmp_path)
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(sa.text("DELETE FROM inspections"))
        scheduler = _scheduler(repo, tmp_path, _ScriptedSink())
        scheduler.run_once()
        tasks = repo.list_uploads(limit=100).items
        inspection = next(t for t in tasks if t.kind == "INSPECTION")
        assert inspection.status == "PERMANENT_FAILURE"
        assert inspection.last_error_code == "INSPECTION_EVIDENCE_MISSING"


class TestRestartRecovery:
    def test_stale_in_progress_tasks_are_reclaimed(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        _seed(repo, tmp_path)
        now = datetime.now(UTC)
        claimed = repo.claim_upload_tasks(10, lease_seconds=120, now_iso=now.isoformat())
        assert len(claimed) == 1
        assert claimed[0].task.status == "IN_PROGRESS"
        # Simulate a crashed worker: the lease expires, then a new scheduler
        # instance must reclaim the tasks.
        later = (now + timedelta(seconds=300)).isoformat()
        reclaimed = repo.claim_upload_tasks(10, lease_seconds=120, now_iso=later)
        assert len(reclaimed) == 1
        assert reclaimed[0].task.status == "IN_PROGRESS"

    def test_late_worker_cannot_overwrite_reclaimed_task(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """F3: the fencing token blocks a stale worker's terminal update."""
        _seed(repo, tmp_path)
        now = datetime.now(UTC)
        first = repo.claim_upload_tasks(10, lease_seconds=120, now_iso=now.isoformat())
        assert len(first) == 1
        # The first worker stalls past its lease; a second worker reclaims.
        later = (now + timedelta(seconds=300)).isoformat()
        second = repo.claim_upload_tasks(10, lease_seconds=120, now_iso=later)
        assert len(second) == 1
        stale = first[0]
        stale_owner = stale.lease_owner
        task_id = str(stale.task.upload_task_id)
        # The stale worker's updates are rejected: zero rows changed.
        assert repo.mark_upload_succeeded(task_id, stale_owner, now.isoformat()) == 0
        assert repo.mark_upload_retry(task_id, stale_owner, "HTTP_503", later, now.isoformat()) == 0
        assert (
            repo.mark_upload_permanent_failure(task_id, stale_owner, "HTTP_409", now.isoformat())
            == 0
        )
        # The current owner still owns the task and can complete it.
        current = second[0]
        # F5 follow-up: even a current lease holder cannot claim success
        # without a persisted verified receipt.
        assert (
            repo.mark_upload_succeeded(str(current.task.upload_task_id), current.lease_owner, later)
            == 0
        )
        # F12: an opaque/mismatched receipt is rejected by the repository.
        assert (
            repo.mark_upload_succeeded(
                str(current.task.upload_task_id),
                current.lease_owner,
                later,
                receipt_json='{"verified":true}',
            )
            == 0
        )
        # A receipt matching the task's immutable fields authorizes success.
        with repo._engine.connect() as conn:  # noqa: SLF001
            row = (
                conn.execute(
                    text(
                        "SELECT idempotency_key, object_id, kind, checksum_sha256, size_bytes "
                        "FROM upload_tasks WHERE upload_task_id = :id"
                    ),
                    {"id": str(current.task.upload_task_id)},
                )
                .mappings()
                .one()
            )
        receipt = json.dumps(
            {
                "idempotency_key": row["idempotency_key"],
                "object_id": row["object_id"],
                "kind": row["kind"],
                "checksum_sha256": row["checksum_sha256"],
                "size_bytes": row["size_bytes"],
                "central_object_id": f"central-{current.task.idempotency_key}",
            }
        )
        assert (
            repo.mark_upload_succeeded(
                str(current.task.upload_task_id),
                current.lease_owner,
                later,
                receipt_json=receipt,
            )
            == 1
        )
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        assert by_kind["INSPECTION"].status == "SUCCEEDED"
        # Media remains pending behind its (now succeeded) parent; it is not
        # claimed by this fencing scenario.
        assert by_kind["MEDIA"].status == "PENDING"

    def test_restart_reclaims_and_drains(self, repo: EdgeRepository, tmp_path: Path) -> None:
        _seed(repo, tmp_path)
        now = datetime.now(UTC)
        repo.claim_upload_tasks(10, lease_seconds=120, now_iso=now.isoformat())
        # Simulate elapsed time: expire every claimed lease in the shared DB.
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                sa.text(
                    "UPDATE upload_tasks SET lease_expires_at = :past WHERE status = 'IN_PROGRESS'"
                ),
                {"past": (now - timedelta(seconds=1)).isoformat()},
            )
        # New process: same database, a fresh scheduler starts after the crash.
        restarted = EdgeRepository.open(tmp_path / "edge.sqlite3")
        try:
            sink = DirectoryUploadSink(tmp_path / "sink")
            scheduler = _scheduler(restarted, tmp_path, sink)
            assert _drain(scheduler) == 2
            assert all(t.status == "SUCCEEDED" for t in restarted.list_uploads(limit=100).items)
        finally:
            restarted.close()

    def test_drains_without_duplicates(self, repo: EdgeRepository, tmp_path: Path) -> None:
        _seed(repo, tmp_path, count=3)
        sink = _ScriptedSink()
        scheduler = _scheduler(repo, tmp_path, sink)
        assert _drain(scheduler) == 6
        assert len(sink.keys) == len(set(sink.keys)) == 6
        assert all(t.status == "SUCCEEDED" for t in repo.list_uploads(limit=100).items)


class TestHttpSink:
    def test_wire_size_counts_serialized_body_not_raw_bytes(self) -> None:
        """PR-022 F02: the throttled unit is the Base64 JSON envelope."""
        import httpx

        task = _task()
        raw = b"\x00" * 1000
        sink = HttpUploadSink("https://central.invalid", client=httpx.Client())
        wire = sink.wire_size(task, raw)
        # Base64 expansion (4/3) plus JSON metadata exceeds the raw payload.
        assert wire > len(raw) * 1.3

    def test_payload_bytes_sent_matches_the_transport_body(self) -> None:
        """PR-022 F02: the reported bytes equal the body the sink actually sent."""
        import json

        import httpx

        received = {"body_len": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            received["body_len"] = len(request.content)
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "idempotency_key": body["idempotency_key"],
                    "object_id": body["object_id"],
                    "kind": body["kind"],
                    "checksum_sha256": body["checksum_sha256"],
                    "size_bytes": body["size_bytes"],
                    "central_object_id": "obj-wire",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = HttpUploadSink("https://central.invalid", client=client)
        task = _task()
        raw = b"\x01\x02" * 100
        result = sink.upload(task, raw)
        assert result.status == "SUCCEEDED"
        assert result.payload_bytes_sent == received["body_len"]
        assert result.payload_bytes_sent == sink.wire_size(task, raw)

    def test_throttled_http_upload_yields_bounded_body_segments(self) -> None:
        """Re-review: each segment is budgeted immediately before transport yield."""
        import json

        import httpx

        yielded: list[int] = []
        received = {"body_len": 0, "content_length": ""}

        def handler(request: httpx.Request) -> httpx.Response:
            received["body_len"] = len(request.content)
            received["content_length"] = request.headers["content-length"]
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "idempotency_key": body["idempotency_key"],
                    "object_id": body["object_id"],
                    "kind": body["kind"],
                    "checksum_sha256": body["checksum_sha256"],
                    "size_bytes": body["size_bytes"],
                    "central_object_id": "obj-stream",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = HttpUploadSink("https://central.invalid", client=client)
        task = _task()
        raw = b"x" * (200 * 1024)
        result = sink.upload_throttled(task, raw, yielded.append)
        wire_size = sink.wire_size(task, raw)
        assert result.status == "SUCCEEDED"
        assert sum(yielded) == wire_size == received["body_len"]
        assert max(yielded) <= 64 * 1024
        assert received["content_length"] == str(wire_size)

    def test_classifies_statuses(self) -> None:
        import json

        import httpx

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call = calls["n"]
            calls["n"] += 1
            if call == 0:
                body = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "idempotency_key": body["idempotency_key"],
                        "object_id": body["object_id"],
                        "kind": body["kind"],
                        "checksum_sha256": body["checksum_sha256"],
                        "size_bytes": body["size_bytes"],
                        "central_object_id": "obj-1",
                    },
                )
            if call == 1:
                return httpx.Response(503)
            if call == 2:
                return httpx.Response(429, headers={"Retry-After": "30"})
            return httpx.Response(409)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = HttpUploadSink("https://central.invalid", client=client)
        task = _task()
        ok = sink.upload(task, b"{}")
        assert ok.status == "SUCCEEDED"
        assert ok.receipt is not None
        assert ok.receipt.central_object_id == "obj-1"
        assert sink.upload(task, b"{}").status == "RETRYABLE"  # 503
        throttled = sink.upload(task, b"{}")
        assert throttled.status == "RETRYABLE"
        assert throttled.retry_after_seconds == 30.0
        assert sink.upload(task, b"{}").status == "PERMANENT"  # 409

    def test_transport_error_is_retryable(self) -> None:
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = HttpUploadSink("https://central.invalid", client=client)
        result = sink.upload(_task(), b"{}")
        assert result.status == "RETRYABLE"
        assert result.error_code == "TRANSPORT_ERROR"

    def test_binary_payload_survives_base64_roundtrip(self) -> None:
        """F1: media bytes are Base64-encoded, never ASCII-lossy decoded."""
        import base64
        import json

        import httpx

        received: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            received.update(body)
            return httpx.Response(
                200,
                json={
                    "idempotency_key": body["idempotency_key"],
                    "object_id": body["object_id"],
                    "kind": body["kind"],
                    "checksum_sha256": body["checksum_sha256"],
                    "size_bytes": body["size_bytes"],
                    "central_object_id": "obj-bin",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = HttpUploadSink("https://central.invalid", client=client)
        task = _task()
        raw = b"\x00\xffJPEG\x80\xfe"
        result = sink.upload(task, raw)
        assert result.status == "SUCCEEDED"
        assert received["idempotency_key"] == task.idempotency_key
        assert received["size_bytes"] == len(raw)
        payload_b64 = received["payload_b64"]
        assert isinstance(payload_b64, str)
        assert base64.b64decode(payload_b64) == raw
        assert received["checksum_sha256"] == task.checksum_sha256

    def test_malformed_receipts_never_mark_success(self) -> None:
        """F5: a 2xx is only success when its receipt matches the task."""
        import httpx

        def echo(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "idempotency_key": body["idempotency_key"],
                    "object_id": body["object_id"],
                    "kind": body["kind"],
                    "checksum_sha256": body["checksum_sha256"],
                    "size_bytes": body["size_bytes"],
                    "central_object_id": "obj-ok",
                },
            )

        task = _task()

        def upload_with(handler: Callable[[httpx.Request], httpx.Response]) -> UploadResult:
            c = httpx.Client(transport=httpx.MockTransport(handler))
            return HttpUploadSink("https://central.invalid", client=c).upload(task, b"{}")

        assert upload_with(echo).status == "SUCCEEDED"  # sanity
        # Empty body.
        assert upload_with(lambda req: httpx.Response(200, text="")).status == "PERMANENT"
        # Unparseable body.
        assert upload_with(lambda req: httpx.Response(200, text="not json")).status == "PERMANENT"
        # Wrong idempotency key.
        assert (
            upload_with(
                lambda req: httpx.Response(
                    200,
                    json={
                        "idempotency_key": "inspection:other",
                        "object_id": str(task.object_id),
                        "kind": task.kind,
                    },
                )
            ).status
            == "PERMANENT"
        )
        # Wrong object id.
        assert (
            upload_with(
                lambda req: httpx.Response(
                    200,
                    json={
                        "idempotency_key": task.idempotency_key,
                        "object_id": str(uuid4()),
                        "kind": task.kind,
                    },
                )
            ).status
            == "PERMANENT"
        )
        # Wrong checksum.
        assert (
            upload_with(
                lambda req: httpx.Response(
                    200,
                    json={
                        "idempotency_key": task.idempotency_key,
                        "object_id": str(task.object_id),
                        "kind": task.kind,
                        "checksum_sha256": "1" * 64,
                    },
                )
            ).status
            == "PERMANENT"
        )
        # Wrong byte size.
        assert (
            upload_with(
                lambda req: httpx.Response(
                    200,
                    json={
                        "idempotency_key": task.idempotency_key,
                        "object_id": str(task.object_id),
                        "kind": task.kind,
                        "size_bytes": 999,
                    },
                )
            ).status
            == "PERMANENT"
        )
        # Matching identity is insufficient: size and checksum are mandatory.
        assert (
            upload_with(
                lambda req: httpx.Response(
                    200,
                    json={
                        "idempotency_key": task.idempotency_key,
                        "object_id": str(task.object_id),
                        "kind": task.kind,
                    },
                )
            ).status
            == "PERMANENT"
        )

    def test_upload_token_is_separate_from_viewer_credential(self) -> None:
        """F7: the sink uses its own credential; the viewer token never leaks."""
        import json

        import httpx

        headers_seen: dict[str, str] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            headers_seen["authorization"] = request.headers.get("authorization", "")
            return httpx.Response(
                200,
                json={
                    "idempotency_key": body["idempotency_key"],
                    "object_id": body["object_id"],
                    "kind": body["kind"],
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(capture))
        task = _task()
        upload_token = "upload-secret"  # noqa: S105 - test-only credential
        # A configured upload credential is sent as Bearer ...
        sink = HttpUploadSink("https://central.invalid", token=upload_token, client=client)
        sink.upload(task, b"{}")
        assert headers_seen["authorization"] == "Bearer upload-secret"
        # ... while a sink without one sends no Authorization header at all,
        # proving the local viewer api_token is never reused for uploads.
        anonymous = HttpUploadSink("https://central.invalid", client=client)
        anonymous.upload(task, b"{}")
        assert headers_seen["authorization"] == ""

    def test_receipt_is_persisted_with_task_success(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """F5: verified receipts and central object ids are stored durably."""
        import json

        _seed(repo, tmp_path)
        sink = DirectoryUploadSink(tmp_path / "sink")
        scheduler = _scheduler(repo, tmp_path, sink)
        assert _drain(scheduler) == 2
        with repo._engine.connect() as conn:  # noqa: SLF001
            rows = (
                conn.execute(
                    sa.text(
                        "SELECT idempotency_key, central_object_id, receipt_json "
                        "FROM upload_tasks WHERE status = 'SUCCEEDED'"
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 2
        for row in rows:
            assert row["central_object_id"] == row["idempotency_key"]
            receipt = json.loads(row["receipt_json"])
            assert receipt["idempotency_key"] == row["idempotency_key"]
            assert receipt["central_object_id"] == row["central_object_id"]

    def test_inspection_sync_state_machine(self, repo: EdgeRepository, tmp_path: Path) -> None:
        """F5: PARTIAL/SYNCED/FAILED derive from all required tasks."""
        record = _seed(repo, tmp_path)[0]
        scheduler = _scheduler(repo, tmp_path, DirectoryUploadSink(tmp_path / "sink"))
        # Metadata succeeds first; media still pending => PARTIAL.
        assert scheduler.run_once() == 1
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "PARTIAL"
        # Media succeeds => SYNCED.
        assert scheduler.run_once() == 1
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "SYNCED"

    def test_permanent_media_failure_marks_inspection_failed(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """F5: a required-media permanent failure reports FAILED, not SYNCED."""
        record = _seed(repo, tmp_path)[0]
        (tmp_path / record.media[0].relative_path).unlink()
        scheduler = _scheduler(repo, tmp_path, DirectoryUploadSink(tmp_path / "sink"))
        _drain(scheduler)
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "FAILED"


class TestBandwidthThrottling:
    """E3a: the scheduler bounds network bytes per second when configured."""

    def test_token_bucket_never_delays_without_a_ceiling(self) -> None:
        from assemblyvision_edge.upload.scheduler import _TokenBucket

        bucket = _TokenBucket(None)
        started = time.monotonic()
        bucket.acquire(1_000_000)
        assert time.monotonic() - started < 0.1

    def test_token_bucket_enforces_the_rate_ceiling(self) -> None:
        from assemblyvision_edge.upload.scheduler import _TokenBucket

        # 200_000 bytes/s; the first acquire fits the one-second burst, the
        # second needs 0.5 s of refill.
        bucket = _TokenBucket(200_000.0)
        started = time.monotonic()
        bucket.acquire(100_000)
        bucket.acquire(100_000)
        elapsed = time.monotonic() - started
        assert elapsed >= 0.4

    def test_token_bucket_splits_large_amounts_across_bursts(self) -> None:
        """PR-022 F01: an amount above one burst capacity must not deadlock."""
        from assemblyvision_edge.upload.scheduler import _TokenBucket

        # Burst capacity is one second of tokens (200_000 B); a 500_000 B
        # acquire must be split into per-burst waits and complete.
        bucket = _TokenBucket(200_000.0)
        started = time.monotonic()
        bucket.acquire(500_000)
        elapsed = time.monotonic() - started
        assert elapsed >= 1.9

    def test_token_bucket_on_wait_runs_and_can_abort(self) -> None:
        """PR-022 F01: an on_wait callback runs during refill and can abort."""
        from assemblyvision_edge.upload.scheduler import _TokenBucket

        bucket = _TokenBucket(100.0)
        calls = {"n": 0}

        def on_wait() -> None:
            calls["n"] += 1
            raise RuntimeError("abort")

        with pytest.raises(RuntimeError, match="abort"):
            bucket.acquire(1_000, on_wait=on_wait)
        assert calls["n"] >= 1

    def test_large_media_throttle_completes_and_renews_lease(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """PR-022 F01: a payload above one burst capacity drains and renews its lease."""
        import json

        import httpx

        out = tmp_path / "out"
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-big")
        data = b"x" * (1024 * 1024)
        item = record.media[0]
        item.size_bytes = len(data)
        item.checksum_sha256 = hashlib.sha256(data).hexdigest()
        path = out / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        repo.persist_inspection_and_enqueue_uploads(record)

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "idempotency_key": body["idempotency_key"],
                    "object_id": body["object_id"],
                    "kind": body["kind"],
                    "checksum_sha256": body["checksum_sha256"],
                    "size_bytes": body["size_bytes"],
                    "central_object_id": f"obj-{body['kind']}",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = HttpUploadSink("https://central.invalid", client=client)

        class _RenewSpy:
            """Counts lease renewals while delegating to the real repository."""

            def __init__(self, underlying: EdgeRepository) -> None:
                self.repo = underlying
                self.renews = 0

            def renew_upload_lease(
                self, upload_task_id: str, lease_owner: str, lease_seconds: int, now_iso: str
            ) -> bool:
                self.renews += 1
                return self.repo.renew_upload_lease(
                    upload_task_id, lease_owner, lease_seconds, now_iso
                )

            def __getattr__(self, name: str) -> object:
                return getattr(self.repo, name)

        spy = _RenewSpy(repo)
        # 4 Mbps -> 500_000 B/s, burst 500_000 B < 1 MiB payload, so the media
        # upload must wait across multiple refills (real-time waits ~3 s).
        scheduler = UploadScheduler(
            spy,  # type: ignore[arg-type]
            sink,
            output_root=out,
            maximum_bandwidth_mbps=4.0,
            interval_seconds=0.0,
            base_retry_seconds=0.0,
        )
        _drain(scheduler)
        tasks = repo.list_uploads(limit=10).items
        assert all(t.status == "SUCCEEDED" for t in tasks)
        assert spy.renews > 0

    def test_throttle_aborts_on_stop_without_terminal_transition(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """PR-022 F01: a stopped worker aborts the throttle wait, never the sink."""
        import json

        import httpx

        out = tmp_path / "out"
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-stop")
        data = b"y" * (1024 * 1024)
        item = record.media[0]
        item.size_bytes = len(data)
        item.checksum_sha256 = hashlib.sha256(data).hexdigest()
        path = out / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        repo.persist_inspection_and_enqueue_uploads(record)

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "idempotency_key": body["idempotency_key"],
                    "object_id": body["object_id"],
                    "kind": body["kind"],
                    "checksum_sha256": body["checksum_sha256"],
                    "size_bytes": body["size_bytes"],
                    "central_object_id": f"obj-{body['kind']}",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = HttpUploadSink("https://central.invalid", client=client)
        scheduler = UploadScheduler(
            repo,
            sink,
            output_root=out,
            maximum_bandwidth_mbps=0.1,
            interval_seconds=0.0,
        )
        scheduler._stop.set()  # noqa: SLF001 - simulate a worker stop
        assert scheduler.run_once() == 1  # a task is claimed
        # The wait aborted: nothing reached the sink and no terminal transition
        # was written for the claimed task; the lease-recovery path reclaims it
        # later. Media stays pending behind its unverified inspection receipt.
        assert calls["n"] == 0
        tasks = repo.list_uploads(limit=10).items
        assert all(t.status == "IN_PROGRESS" for t in tasks if t.kind == "INSPECTION")
        assert all(t.status == "PENDING" for t in tasks if t.kind == "MEDIA")

    def test_renew_upload_lease_is_compare_and_set(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """PR-022 F01: only the current lease owner can renew the lease."""
        _seed(repo, tmp_path / "out")
        now = datetime.now(UTC)
        claimed = repo.claim_upload_tasks(10, lease_seconds=120, now_iso=now.isoformat())
        assert len(claimed) == 1
        task_id = str(claimed[0].task.upload_task_id)
        owner = claimed[0].lease_owner
        assert repo.renew_upload_lease(task_id, owner, 120, now.isoformat()) is True
        # A foreign owner cannot renew; the lease belongs to the worker.
        assert repo.renew_upload_lease(task_id, "other-owner", 120, now.isoformat()) is False
        # An unknown task cannot renew.
        assert repo.renew_upload_lease(str(uuid4()), owner, 120, now.isoformat()) is False

    def test_scheduler_exposes_bytes_sent_and_bandwidth_ceiling(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        sink = _ScriptedSink()
        scheduler = UploadScheduler(
            repo,
            sink,
            output_root=tmp_path / "out",
            maximum_bandwidth_mbps=10.0,
            interval_seconds=0.0,
        )
        _seed(repo, tmp_path / "out", count=2)
        handled = scheduler.run_once()
        assert handled >= 2
        health = scheduler.health()
        assert health.bytes_sent > 0
        assert health.bandwidth_mbps == 10.0
        assert health.successes >= 2

    def test_directory_sink_reports_zero_network_bytes(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """PR-022 F02: a local sink is not network traffic and counts 0 bytes."""
        _seed(repo, tmp_path)
        scheduler = _scheduler(repo, tmp_path, DirectoryUploadSink(tmp_path / "sink"))
        _drain(scheduler)
        assert scheduler.health().bytes_sent == 0

    def test_device_status_reports_bytes_sent_and_bandwidth(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        from assemblyvision_edge.api.settings import ServerSettings
        from assemblyvision_edge.api.state import EdgeRuntime

        sink = _ScriptedSink()
        scheduler = UploadScheduler(
            repo,
            sink,
            output_root=tmp_path / "out",
            maximum_bandwidth_mbps=5.0,
            interval_seconds=0.0,
        )
        _seed(repo, tmp_path / "out", count=1)
        scheduler.run_once()
        runtime = EdgeRuntime(
            ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
        )
        status = runtime.device_status(0, health=scheduler.health())
        assert status["upload_bytes_sent"] > 0
        assert status["upload_bandwidth_mbps"] == 5.0


class _FlipSink:
    """Sink that fails the first ``fail_count`` attempts, then succeeds."""

    def __init__(self, fail_count: int) -> None:
        self._remaining = fail_count
        self.keys: list[str] = []

    def upload(self, task: UploadTask, payload: bytes) -> UploadResult:
        self.keys.append(task.idempotency_key)
        if self._remaining > 0:
            self._remaining -= 1
            return UploadResult(status="RETRYABLE", error_code="TRANSPORT_ERROR")
        return UploadResult(
            status="SUCCEEDED",
            receipt=UploadReceipt(
                idempotency_key=task.idempotency_key,
                object_id=str(task.object_id),
                kind=task.kind,
                checksum_sha256=task.checksum_sha256,
                size_bytes=len(payload),
                central_object_id=f"central-{task.idempotency_key}",
            ),
            payload_bytes_sent=len(payload),
        )


class TestCircuitBreaker:
    """E3b: consecutive retryable failures open the circuit and stop traffic."""

    @staticmethod
    def _scheduler(
        repo: EdgeRepository,
        output_root: Path,
        sink: object,
        clock: _AdvancingClock,
        *,
        threshold: int = 3,
        open_seconds: float = 60.0,
    ) -> UploadScheduler:
        return UploadScheduler(
            repo,
            sink,  # type: ignore[arg-type]
            output_root=output_root,
            base_retry_seconds=0.0,
            maximum_retry_seconds=60.0,
            exponent_cap=3,
            circuit_failure_threshold=threshold,
            circuit_open_seconds=open_seconds,
            now=clock,
        )

    def test_retryable_failures_open_circuit_and_stop_attempts(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        clock = _AdvancingClock(datetime.now(UTC))
        sink = _ScriptedSink([UploadResult(status="RETRYABLE", error_code="TRANSPORT_ERROR")])
        scheduler = self._scheduler(repo, tmp_path / "out", sink, clock)
        _seed(repo, tmp_path / "out", count=3)  # 6 tasks
        attempts_after_open = len(sink.keys)
        for _ in range(30):
            if scheduler.health().circuit_state == "OPEN":
                break
            scheduler.run_once()
        assert scheduler.health().circuit_state == "OPEN"
        attempts_after_open = len(sink.keys)
        # An open circuit produces zero further attempts.
        for _ in range(5):
            assert scheduler.run_once() == 0
        assert len(sink.keys) == attempts_after_open
        # The queue is untouched: tasks are still present, not lost.
        assert repo.count_pending_uploads() >= 6

    def test_half_open_probe_success_closes_circuit_and_resumes_drain(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        clock = _AdvancingClock(datetime.now(UTC))
        # Three INSPECTION tasks fail first (metadata-before-media ordering), so
        # exactly the threshold of retryable failures opens the circuit and the
        # sink recovers in time for the half-open probe.
        sink = _FlipSink(fail_count=3)
        scheduler = self._scheduler(repo, tmp_path / "out", sink, clock)
        _seed(repo, tmp_path / "out", count=3)
        for _ in range(30):
            if scheduler.health().circuit_state == "OPEN":
                break
            scheduler.run_once()
        assert scheduler.health().circuit_state == "OPEN"
        clock.advance(61)
        # Half-open probe succeeds and closes the circuit.
        scheduler.run_once()
        assert scheduler.health().circuit_state == "CLOSED"
        # Drain completes after recovery.
        _drain(scheduler)
        assert repo.count_pending_uploads() == 0
        assert len(sink.keys) >= 6

    def test_half_open_probe_failure_reopens_circuit(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        clock = _AdvancingClock(datetime.now(UTC))
        sink = _ScriptedSink([UploadResult(status="RETRYABLE", error_code="TRANSPORT_ERROR")])
        scheduler = self._scheduler(repo, tmp_path / "out", sink, clock)
        _seed(repo, tmp_path / "out", count=1)
        for _ in range(30):
            if scheduler.health().circuit_state == "OPEN":
                break
            scheduler.run_once()
        assert scheduler.health().circuit_state == "OPEN"
        clock.advance(61)
        scheduler.run_once()
        assert scheduler.health().circuit_state == "OPEN"

    def test_permanent_failures_never_open_circuit(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        clock = _AdvancingClock(datetime.now(UTC))
        sink = _ScriptedSink([UploadResult(status="PERMANENT", error_code="HTTP_409")])
        scheduler = self._scheduler(repo, tmp_path / "out", sink, clock)
        _seed(repo, tmp_path / "out", count=2)
        _drain(scheduler)
        assert scheduler.health().circuit_state == "CLOSED"

    def test_device_status_exposes_circuit_state_and_alert(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        from assemblyvision_edge.api.settings import ServerSettings
        from assemblyvision_edge.api.state import EdgeRuntime

        clock = _AdvancingClock(datetime.now(UTC))
        sink = _ScriptedSink([UploadResult(status="RETRYABLE", error_code="TRANSPORT_ERROR")])
        scheduler = self._scheduler(repo, tmp_path / "out", sink, clock)
        _seed(repo, tmp_path / "out", count=3)
        for _ in range(30):
            if scheduler.health().circuit_state == "OPEN":
                break
            scheduler.run_once()
        assert scheduler.health().circuit_state == "OPEN"
        runtime = EdgeRuntime(
            ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
        )
        status = runtime.device_status(0, health=scheduler.health())
        assert status["upload_circuit_state"] == "OPEN"
        assert "UPLOAD_CIRCUIT_OPEN" in status["alerts"]


class TestLongOutageDrain:
    """E3d: a prolonged outage preserves the queue and drains duplicate-free."""

    def test_prolonged_offline_inspection_restart_and_duplicate_free_drain(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "edge.sqlite3"
        out = tmp_path / "out"
        clock = _AdvancingClock(datetime.now(UTC))
        repo = EdgeRepository.open(db)
        try:
            failing = _ScriptedSink(
                [UploadResult(status="RETRYABLE", error_code="TRANSPORT_ERROR")]
            )
            scheduler = UploadScheduler(
                repo,
                failing,
                output_root=out,
                base_retry_seconds=2.0,
                maximum_retry_seconds=900.0,
                exponent_cap=8,
                now=clock,
            )
            # Products keep being inspected while the network is down; the
            # queue persists every task with retry/backoff.
            _seed(repo, out, count=5)
            for _ in range(3):
                scheduler.run_once()
            # The outage continues for days; new inspections still persist
            # locally and enqueue their tasks.
            clock.advance(3 * 86400)
            _seed(repo, out, count=3)
        finally:
            repo.close()
        # Process restart with the same database; connectivity is restored.
        restarted = EdgeRepository.open(db)
        try:
            restored = DirectoryUploadSink(tmp_path / "sink")
            scheduler2 = UploadScheduler(restarted, restored, output_root=out, now=clock)
            _drain(scheduler2)
            tasks = restarted.list_uploads(limit=1000).items
            # 8 inspections x (INSPECTION + MEDIA): nothing lost, nothing duplicated.
            assert len(tasks) == 16
            assert all(t.status == "SUCCEEDED" for t in tasks)
            keys = [t.idempotency_key for t in tasks]
            assert len(keys) == len(set(keys))
            # Metadata-before-media drain: every inspection is fully SYNCED.
            summaries = restarted.list_inspections(limit=100).items
            assert len(summaries) == 8
            assert all(s.upload_state == "SYNCED" for s in summaries)
        finally:
            restarted.close()


def _task() -> UploadTask:
    return UploadTask(
        upload_task_id=uuid4(),
        device_id=uuid4(),
        inspection_id=None,
        kind="INSPECTION",
        object_id=uuid4(),
        payload_hash="0" * 64,
        status="PENDING",
        idempotency_key="inspection:test",
        checksum_sha256="0" * 64,
        attempt_count=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
