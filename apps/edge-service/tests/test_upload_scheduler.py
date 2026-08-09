"""Persistent upload outbox and scheduler tests (contract 06 section 6).

Covers the required upload-queue cases: successful upload, network
interruption, retry, duplicate upload, process restart, missing file, checksum
mismatch, server idempotency conflict, and recovery of stale IN_PROGRESS
tasks (design 13.5/13.9, ADR-005).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
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
    UploadResult,
    UploadScheduler,
    _full_jitter_backoff,
)

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


class TestSuccessfulUpload:
    def test_scheduler_drains_to_sink(self, repo: EdgeRepository, tmp_path: Path) -> None:
        record = _seed(repo, tmp_path)[0]
        sink_dir = tmp_path / "sink"
        sink = DirectoryUploadSink(sink_dir)
        scheduler = _scheduler(repo, tmp_path, sink)
        handled = scheduler.run_once()
        assert handled == 2
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
        assert len(claimed) == 2
        assert all(item.task.status == "IN_PROGRESS" for item in claimed)
        # F3: every claim carries a distinct fencing token.
        assert len({item.lease_owner for item in claimed}) == 2


class TestRetryBehavior:
    def test_network_interruption_schedules_retry(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        _seed(repo, tmp_path)
        sink = _ScriptedSink([UploadResult(status="RETRYABLE", error_code="TRANSPORT_ERROR")])
        scheduler = _scheduler(repo, tmp_path, sink)
        now = datetime.now(UTC)
        assert scheduler.run_once() == 2
        tasks = repo.list_uploads(limit=100).items
        assert all(task.status == "RETRY_WAIT" for task in tasks)
        assert all(task.attempt_count == 1 for task in tasks)
        assert all(task.last_error_code == "TRANSPORT_ERROR" for task in tasks)
        for task in tasks:
            assert task.next_attempt_at is not None
            assert task.next_attempt_at > now

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
        # run_once calls exercise the full retry ladder.
        scheduler = _scheduler(repo, tmp_path, sink, base_retry_seconds=0.0)
        scheduler.run_once()  # attempt 1: both retryable
        tasks = repo.list_uploads(limit=100).items
        assert all(t.status == "RETRY_WAIT" for t in tasks)
        for _ in range(4):
            scheduler.run_once()
            if all(t.status == "SUCCEEDED" for t in repo.list_uploads(limit=100).items):
                break
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
        tasks = repo.list_uploads(limit=100).items
        assert all(t.status == "RETRY_WAIT" for t in tasks)
        for task in tasks:
            assert task.next_attempt_at is not None
            assert task.next_attempt_at >= now + timedelta(seconds=60)

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
        scheduler.run_once()
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        assert by_kind["MEDIA"].status == "PERMANENT_FAILURE"
        assert by_kind["MEDIA"].last_error_code == "MEDIA_EVIDENCE_MISSING"
        # Metadata upload still succeeds; local evidence is preserved.
        assert by_kind["INSPECTION"].status == "SUCCEEDED"

    def test_checksum_mismatch_is_permanent_failure(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        record = _seed(repo, tmp_path)[0]
        (tmp_path / record.media[0].relative_path).write_bytes(b"corrupted-bytes")
        scheduler = _scheduler(repo, tmp_path, _ScriptedSink())
        scheduler.run_once()
        by_kind = _by_kind(repo.list_uploads(limit=100).items)
        assert by_kind["MEDIA"].status == "PERMANENT_FAILURE"
        assert by_kind["MEDIA"].last_error_code == "MEDIA_CHECKSUM_MISMATCH"

    def test_server_idempotency_conflict_is_permanent(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        _seed(repo, tmp_path)
        sink = _ScriptedSink([UploadResult(status="PERMANENT", error_code="HTTP_409")])
        scheduler = _scheduler(repo, tmp_path, sink)
        scheduler.run_once()
        tasks = repo.list_uploads(limit=100).items
        assert all(t.status == "PERMANENT_FAILURE" for t in tasks)
        assert all(t.last_error_code == "HTTP_409" for t in tasks)

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
        tasks = repo.claim_upload_tasks(10, lease_seconds=120, now_iso=now.isoformat())
        assert all(t.task.status == "IN_PROGRESS" for t in tasks)
        # Simulate a crashed worker: the lease expires, then a new scheduler
        # instance must reclaim the tasks.
        later = (now + timedelta(seconds=300)).isoformat()
        reclaimed = repo.claim_upload_tasks(10, lease_seconds=120, now_iso=later)
        assert len(reclaimed) == 2
        assert all(t.task.status == "IN_PROGRESS" for t in reclaimed)

    def test_late_worker_cannot_overwrite_reclaimed_task(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """F3: the fencing token blocks a stale worker's terminal update."""
        _seed(repo, tmp_path)
        now = datetime.now(UTC)
        first = repo.claim_upload_tasks(10, lease_seconds=120, now_iso=now.isoformat())
        assert len(first) == 2
        # The first worker stalls past its lease; a second worker reclaims.
        later = (now + timedelta(seconds=300)).isoformat()
        second = repo.claim_upload_tasks(10, lease_seconds=120, now_iso=later)
        assert len(second) == 2
        for stale in first:
            stale_owner = stale.lease_owner
            task_id = str(stale.task.upload_task_id)
            # The stale worker's updates are rejected: zero rows changed.
            assert repo.mark_upload_succeeded(task_id, stale_owner, now.isoformat()) == 0
            assert (
                repo.mark_upload_retry(task_id, stale_owner, "HTTP_503", later, now.isoformat())
                == 0
            )
            assert (
                repo.mark_upload_permanent_failure(
                    task_id, stale_owner, "HTTP_409", now.isoformat()
                )
                == 0
            )
        # The current owner still owns the tasks and can complete them.
        for current in second:
            assert (
                repo.mark_upload_succeeded(
                    str(current.task.upload_task_id), current.lease_owner, later
                )
                == 1
            )
        assert all(t.status == "SUCCEEDED" for t in repo.list_uploads(limit=100).items)

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
            assert scheduler.run_once() == 2
            assert all(t.status == "SUCCEEDED" for t in restarted.list_uploads(limit=100).items)
        finally:
            restarted.close()

    def test_drains_without_duplicates(self, repo: EdgeRepository, tmp_path: Path) -> None:
        _seed(repo, tmp_path, count=3)
        sink = _ScriptedSink()
        scheduler = _scheduler(repo, tmp_path, sink)
        for _ in range(10):
            if scheduler.run_once() == 0:
                break
        assert len(sink.keys) == len(set(sink.keys)) == 6
        assert all(t.status == "SUCCEEDED" for t in repo.list_uploads(limit=100).items)


class TestHttpSink:
    def test_classifies_statuses(self) -> None:
        import httpx

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call = calls["n"]
            calls["n"] += 1
            if call == 0:
                return httpx.Response(200, text="receipt-ok")
            if call == 1:
                return httpx.Response(503)
            if call == 2:
                return httpx.Response(429, headers={"Retry-After": "30"})
            return httpx.Response(409)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = HttpUploadSink("http://central.invalid", client=client)
        task = _task()
        assert sink.upload(task, b"{}").status == "SUCCEEDED"
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
        sink = HttpUploadSink("http://central.invalid", client=client)
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
            received.update(json.loads(request.content))
            return httpx.Response(200, text="receipt-ok")

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
        attempt_count=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
