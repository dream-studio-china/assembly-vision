"""Manual upload retry endpoint tests (E3 task invariant 3, E3c).

Covers the controlled retry boundary: only RETRY_WAIT / PERMANENT_FAILURE
tasks reset to PENDING with an incremented attempt count; unknown tasks are
404 and non-eligible tasks are 409 without mutation; a retried task re-drains
idempotently.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.models import BusinessResult, UploadTask
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.persistence.repository import EdgeRepository
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.test_api import _record


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EdgeRepository]:
    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        yield repository
    finally:
        repository.close()


def _seed_task(repo: EdgeRepository, status: str) -> UploadTask:
    """Persist one inspection and force its INSPECTION task to ``status``."""
    record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode=f"SN-{uuid4()}")
    repo.persist_inspection_and_enqueue_uploads(record)
    with repo._engine.begin() as conn:  # noqa: SLF001
        conn.execute(
            text(
                "UPDATE upload_tasks SET status = :status "
                "WHERE kind = 'INSPECTION' AND inspection_id = :id"
            ),
            {"status": status, "id": str(record.inspection_id)},
        )
    tasks = repo.list_uploads(limit=10).items
    target = next(
        t for t in tasks if t.kind == "INSPECTION" and t.inspection_id == record.inspection_id
    )
    return target


def _client(tmp_path: Path, repo: EdgeRepository) -> TestClient:
    app = create_app(
        ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    )
    client = TestClient(app)
    app.state.repository = repo
    return client


class TestManualRetry:
    def test_retry_eligible_task_resets_and_increments_attempts(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        task = _seed_task(repo, "RETRY_WAIT")
        client = _client(tmp_path, repo)
        try:
            response = client.post(f"/api/v1/uploads/{task.upload_task_id}/retry")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "PENDING"
            assert body["attempt_count"] == task.attempt_count + 1
            assert body["upload_task_id"] == str(task.upload_task_id)
        finally:
            client.close()

    def test_retry_with_reason_succeeds_and_logs_operator_reason(
        self, repo: EdgeRepository, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """E3c: a manual retry carries an optional operator reason (audit log)."""
        task = _seed_task(repo, "RETRY_WAIT")
        client = _client(tmp_path, repo)
        try:
            with caplog.at_level(logging.INFO, logger="assemblyvision.repository"):
                response = client.post(
                    f"/api/v1/uploads/{task.upload_task_id}/retry",
                    json={"reason": "  operator cleared conveyor jam  "},
                )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "PENDING"
            assert body["attempt_count"] == task.attempt_count + 1
            # Whitespace is stripped and the reason reaches the repository log.
            assert "operator cleared conveyor jam" in caplog.text
        finally:
            client.close()

    def test_retry_without_body_is_backward_compatible(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """E3c: a legacy retry with no body still succeeds with an empty reason."""
        task = _seed_task(repo, "RETRY_WAIT")
        client = _client(tmp_path, repo)
        try:
            response = client.post(
                f"/api/v1/uploads/{task.upload_task_id}/retry",
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "PENDING"
        finally:
            client.close()

    def test_retry_with_too_long_reason_is_422_without_mutation(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """A reason over the schema bound is rejected before any transition."""
        task = _seed_task(repo, "RETRY_WAIT")
        client = _client(tmp_path, repo)
        try:
            response = client.post(
                f"/api/v1/uploads/{task.upload_task_id}/retry",
                json={"reason": "x" * 201},
            )
            assert response.status_code == 422
        finally:
            client.close()
        refreshed = repo.get_upload_task(str(task.upload_task_id))
        assert refreshed is not None
        assert refreshed.status == "RETRY_WAIT"
        assert refreshed.attempt_count == task.attempt_count

    def test_retry_permanent_failure_is_eligible(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        task = _seed_task(repo, "PERMANENT_FAILURE")
        client = _client(tmp_path, repo)
        try:
            response = client.post(f"/api/v1/uploads/{task.upload_task_id}/retry")
            assert response.status_code == 200
            assert response.json()["status"] == "PENDING"
        finally:
            client.close()

    def test_retry_non_eligible_state_is_409_without_mutation(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        task = _seed_task(repo, "SUCCEEDED")
        client = _client(tmp_path, repo)
        try:
            response = client.post(f"/api/v1/uploads/{task.upload_task_id}/retry")
            assert response.status_code == 409
            assert response.json()["code"] == "TASK_NOT_RETRYABLE"
        finally:
            client.close()
        # The task was not mutated.
        refreshed = repo.get_upload_task(str(task.upload_task_id))
        assert refreshed is not None
        assert refreshed.status == "SUCCEEDED"
        assert refreshed.attempt_count == task.attempt_count

    def test_retry_unknown_task_is_404(self, tmp_path: Path) -> None:
        repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
        try:
            client = _client(tmp_path, repo)
            try:
                response = client.post(f"/api/v1/uploads/{uuid4()}/retry")
                assert response.status_code == 404
            finally:
                client.close()
        finally:
            repo.close()

    def test_retried_task_drains_idempotently(self, repo: EdgeRepository, tmp_path: Path) -> None:
        from assemblyvision_edge.upload.scheduler import (
            DirectoryUploadSink,
            UploadScheduler,
        )

        task = _seed_task(repo, "PERMANENT_FAILURE")
        client = _client(tmp_path, repo)
        try:
            response = client.post(f"/api/v1/uploads/{task.upload_task_id}/retry")
            assert response.status_code == 200
        finally:
            client.close()
        sink_dir = tmp_path / "sink"
        scheduler = UploadScheduler(
            repo, DirectoryUploadSink(sink_dir), output_root=tmp_path / "out"
        )
        for _ in range(10):
            scheduler.run_once()
        refreshed = repo.get_upload_task(str(task.upload_task_id))
        assert refreshed is not None
        assert refreshed.status == "SUCCEEDED"

    def test_second_retry_of_same_task_is_409_not_false_200(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """PR-022 F03: a repeated retry cannot succeed twice (CAS transition)."""
        task = _seed_task(repo, "RETRY_WAIT")
        client = _client(tmp_path, repo)
        try:
            first = client.post(f"/api/v1/uploads/{task.upload_task_id}/retry")
            assert first.status_code == 200
            second = client.post(f"/api/v1/uploads/{task.upload_task_id}/retry")
            assert second.status_code == 409
            assert second.json()["code"] == "TASK_NOT_RETRYABLE"
        finally:
            client.close()
        refreshed = repo.get_upload_task(str(task.upload_task_id))
        assert refreshed is not None
        assert refreshed.status == "PENDING"
        assert refreshed.attempt_count == task.attempt_count + 1

    def test_concurrent_retries_have_single_winner(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """PR-022 F03: two simultaneous retries yield one transition, one 409."""
        import threading

        task = _seed_task(repo, "RETRY_WAIT")
        outcomes: list[str] = []
        lock = threading.Lock()

        def attempt() -> None:
            result = repo.retry_upload(
                str(task.upload_task_id), "manual", datetime.now(UTC).isoformat()
            )
            with lock:
                outcomes.append(result.outcome)

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(outcomes) == ["NOT_RETRYABLE", "RETRIED"]
        refreshed = repo.get_upload_task(str(task.upload_task_id))
        assert refreshed is not None
        assert refreshed.status == "PENDING"
        assert refreshed.attempt_count == task.attempt_count + 1

    def test_retry_clears_terminal_and_retry_fields(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """PR-022 F03: retry clears completed/retry/lease fields and stamps updated_at."""
        task = _seed_task(repo, "PERMANENT_FAILURE")
        now_iso = datetime.now(UTC).isoformat()
        result = repo.retry_upload(str(task.upload_task_id), "manual", now_iso)
        assert result.outcome == "RETRIED"
        assert result.task is not None
        assert result.task.status == "PENDING"
        assert result.task.completed_at is None
        assert result.task.next_attempt_at is None
        assert result.task.last_error_code is None
        assert result.task.updated_at == datetime.fromisoformat(now_iso)

    def test_retried_permanent_media_refreshes_inspection_sync(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """PR-022 F03: retrying a permanent media task recomputes inspection sync."""
        import hashlib

        from assemblyvision_edge.upload.scheduler import DirectoryUploadSink, UploadScheduler

        out = tmp_path / "out"
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-sync")
        for item in record.media:
            path = out / item.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            data = f"jpeg-bytes-{item.media_id}".encode()
            path.write_bytes(data)
            item.size_bytes = len(data)
            item.checksum_sha256 = hashlib.sha256(data).hexdigest()
        repo.persist_inspection_and_enqueue_uploads(record)

        # Missing media makes the media task permanent and the inspection FAILED.
        media_path = out / record.media[0].relative_path
        media_bytes = media_path.read_bytes()
        media_path.unlink()
        scheduler = UploadScheduler(repo, DirectoryUploadSink(tmp_path / "sink"), output_root=out)
        for _ in range(10):
            scheduler.run_once()
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "FAILED"

        # Restore the media and retry it: aggregate sync returns to PARTIAL
        # immediately (the metadata receipt is still verified).
        media_path.write_bytes(media_bytes)
        media_task = next(t for t in repo.list_uploads(limit=10).items if t.kind == "MEDIA")
        result = repo.retry_upload(
            str(media_task.upload_task_id), "manual", datetime.now(UTC).isoformat()
        )
        assert result.outcome == "RETRIED"
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "PARTIAL"

        # The retried task drains idempotently to SYNCED.
        for _ in range(10):
            scheduler.run_once()
        fetched = repo.get_inspection(str(record.inspection_id))
        assert fetched is not None
        assert fetched.synchronization_status == "SYNCED"
