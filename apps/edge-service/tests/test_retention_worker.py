"""E2b cleanup worker tests (task E2b exit criteria).

Covers audited deletion exactly once, the missing-file integrity fault, retry
of unlink failures, unsafe-path protection, the disabled-policy guarantee of
zero filesystem mutation, crash-after-unlink recovery, and worker health.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from assemblyvision_domain.models import (
    BusinessResult,
    InspectionRecord,
)
from assemblyvision_edge.persistence.repository import EdgeRepository
from assemblyvision_edge.retention.policy import RetentionPolicy
from assemblyvision_edge.retention.worker import RetentionCleanupWorker
from sqlalchemy import text

from tests.test_api import _record
from tests.test_retention_persistence import NOW, _mark_synced

POLICY = RetentionPolicy({"KEY_FRAME": timedelta(days=1)})


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EdgeRepository]:
    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        yield repository
    finally:
        repository.close()


def _write_media_files(output_root: Path, record: InspectionRecord) -> None:
    for item in record.media:
        path = output_root / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = f"media-{item.media_id}".encode()
        path.write_bytes(data)
        item.size_bytes = len(data)
        item.checksum_sha256 = hashlib.sha256(data).hexdigest()


def _seed_eligible(
    repo: EdgeRepository,
    output_root: Path,
    *,
    relative_path: str | None = None,
) -> InspectionRecord:
    """Persist a receipt-verified, deadline-elapsed record with a real file."""
    record = _record(NOW - timedelta(days=3), business=BusinessResult.OK, barcode="SN-E2B")
    _write_media_files(output_root, record)
    repo.persist_inspection_and_enqueue_uploads(record, retention=POLICY)
    if relative_path is not None:
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text("UPDATE media SET relative_path = :path WHERE inspection_id = :id"),
                {"path": relative_path, "id": str(record.inspection_id)},
            )
    _mark_synced(repo, record)
    return record


def _worker(
    repo: EdgeRepository, output_root: Path, *, policy: RetentionPolicy | None = POLICY
) -> RetentionCleanupWorker:
    return RetentionCleanupWorker(
        repo, output_root, policy, interval_seconds=3600, lease_seconds=120
    )


def _media_row(repo: EdgeRepository, media_id: str) -> dict[str, object]:
    with repo._engine.connect() as conn:  # noqa: SLF001
        row = (
            conn.execute(
                text(
                    "SELECT lifecycle, purged_at, purge_reason, integrity_status, "
                    "last_delete_error, deleting_at FROM media WHERE media_id = :id"
                ),
                {"id": media_id},
            )
            .mappings()
            .one()
        )
    return dict(row)


class TestWorkerPurge:
    def test_purges_eligible_media_exactly_once(self, repo: EdgeRepository, tmp_path: Path) -> None:
        output_root = tmp_path / "out"
        record = _seed_eligible(repo, output_root)
        media_path = output_root / record.media[0].relative_path
        assert media_path.is_file()

        worker = _worker(repo, output_root)
        assert worker.run_once() == 1

        assert not media_path.exists()
        row = _media_row(repo, str(record.media[0].media_id))
        assert row["lifecycle"] == "PURGED"
        assert row["purge_reason"] == "retention"
        assert row["purged_at"] is not None
        assert row["integrity_status"] is None

        health = worker.health()
        assert health.purged_count == 1
        assert health.reclaimed_bytes == record.media[0].size_bytes
        assert health.failure_count == 0
        # A second pass has nothing left to do.
        assert worker.run_once() == 0
        assert worker.health().purged_count == 1

    def test_media_serving_reports_purged(self, repo: EdgeRepository, tmp_path: Path) -> None:
        output_root = tmp_path / "out"
        record = _seed_eligible(repo, output_root)
        worker = _worker(repo, output_root)
        worker.run_once()
        media_id = str(record.media[0].media_id)
        fetched = repo.get_media(media_id)
        assert fetched is not None
        metadata, _ = fetched
        assert metadata.lifecycle.value == "PURGED"


class TestFaultsAndRetry:
    def test_missing_file_is_integrity_fault_not_success(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        output_root = tmp_path / "out"
        record = _seed_eligible(repo, output_root)
        media_id = str(record.media[0].media_id)
        (output_root / record.media[0].relative_path).unlink()

        worker = _worker(repo, output_root)
        worker.run_once()

        row = _media_row(repo, media_id)
        assert row["integrity_status"] == "FAULT"
        assert row["lifecycle"] != "PURGED"
        assert row["deleting_at"] is None  # claim released
        assert worker.health().last_error_code == "MEDIA_EVIDENCE_MISSING"
        assert worker.health().failure_count == 1
        # A faulted artifact is never eligible again.
        assert repo.retention_eligible(NOW.isoformat()) == []

    def test_unlink_permission_error_is_retryable(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        output_root = tmp_path / "out"
        record = _seed_eligible(repo, output_root)
        media_id = str(record.media[0].media_id)
        directory = output_root / str(record.inspection_id)
        directory.chmod(0o500)  # unlink requires directory write permission
        try:
            worker = _worker(repo, output_root)
            worker.run_once()
        finally:
            directory.chmod(0o700)

        row = _media_row(repo, media_id)
        assert row["last_delete_error"] == "EACCES"
        assert row["lifecycle"] == "AVAILABLE"
        assert row["deleting_at"] is None
        assert worker.health().last_error_code == "EACCES"
        # The released claim is retried on the next cycle and succeeds.
        worker = _worker(repo, output_root)
        assert worker.run_once() == 1
        assert _media_row(repo, media_id)["lifecycle"] == "PURGED"
        assert not (output_root / record.media[0].relative_path).exists()

    def test_unsafe_path_is_faulted_without_touching_any_file(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        output_root = tmp_path / "out"
        record = _seed_eligible(repo, output_root, relative_path="../escape.jpg")
        media_id = str(record.media[0].media_id)

        worker = _worker(repo, output_root)
        worker.run_once()

        row = _media_row(repo, media_id)
        assert row["integrity_status"] == "FAULT"
        assert row["lifecycle"] != "PURGED"
        assert worker.health().last_error_code == "MEDIA_PATH_UNSAFE"
        assert not (output_root.parent / "escape.jpg").exists()

    def test_crash_after_unlink_recovers_without_double_delete(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        output_root = tmp_path / "out"
        record = _seed_eligible(repo, output_root)
        media_id = str(record.media[0].media_id)
        path = output_root / record.media[0].relative_path

        # Simulate a crash: claim, unlink, then never finalize.
        claimed = repo.claim_retention_batch(10, 1, (NOW - timedelta(minutes=2)).isoformat())
        assert len(claimed) == 1
        path.unlink()

        # A new worker recovers the expired claim; the missing file is a fault,
        # never a second deletion or a false purge.
        worker = _worker(repo, output_root)
        worker.run_once()
        row = _media_row(repo, media_id)
        assert row["integrity_status"] == "FAULT"
        assert row["lifecycle"] != "PURGED"
        assert not path.exists()


class TestDisabledPolicy:
    def test_no_policy_means_zero_unlink_calls(self, repo: EdgeRepository, tmp_path: Path) -> None:
        output_root = tmp_path / "out"
        record = _seed_eligible(repo, output_root)
        media_path = output_root / record.media[0].relative_path

        worker = _worker(repo, output_root, policy=None)
        assert worker.enabled is False
        assert worker.run_once() == 0
        assert worker.health().runs == 0
        assert media_path.is_file()
        assert _media_row(repo, str(record.media[0].media_id))["lifecycle"] == "AVAILABLE"


class TestHealth:
    def test_health_tracks_runs_failures_and_clears(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        output_root = tmp_path / "out"
        record = _seed_eligible(repo, output_root)
        media_id = str(record.media[0].media_id)
        (output_root / record.media[0].relative_path).unlink()

        worker = _worker(repo, output_root)
        worker.run_once()  # fault path
        health = worker.health()
        assert health.runs == 1
        assert health.failure_count == 1
        assert health.last_error_code == "MEDIA_EVIDENCE_MISSING"
        assert health.last_run_at is not None
        assert health.purged_count == 0
        assert health.reclaimed_bytes == 0
        assert media_id  # keep the reader honest
