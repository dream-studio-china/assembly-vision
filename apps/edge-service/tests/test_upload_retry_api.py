"""Manual upload retry endpoint tests (E3 task invariant 3, E3c).

Covers the controlled retry boundary: only RETRY_WAIT / PERMANENT_FAILURE
tasks reset to PENDING with an incremented attempt count; unknown tasks are
404 and non-eligible tasks are 409 without mutation; a retried task re-drains
idempotently.
"""

from __future__ import annotations

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
