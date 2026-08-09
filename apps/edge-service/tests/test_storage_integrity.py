"""E2d startup integrity, quarantine, and recovery tests (task E2d exit criteria).

Covers the media/filesystem integrity scan (missing file, size mismatch,
checksum mismatch, unsafe path), durable quarantine of malformed/conflicting
bundles, the SQLite quick_check fail-closed gate, abandoned cleanup-claim
recovery, and integrity-fault visibility in metrics.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.models import (
    BusinessResult,
    InspectionRecord,
    MediaLifecycle,
    MediaMetadata,
)
from assemblyvision_edge.persistence.reconcile import (
    reconcile_output_root,
    scan_storage_integrity,
)
from assemblyvision_edge.persistence.repository import EdgeRepository
from assemblyvision_edge.retention.policy import RetentionPolicy
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


def _write_media_file(output_root: Path, record: InspectionRecord, item: MediaMetadata) -> None:
    path = output_root / item.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = f"bytes-{item.media_id}".encode()
    path.write_bytes(data)
    item.size_bytes = len(data)
    item.checksum_sha256 = hashlib.sha256(data).hexdigest()


def _seed_media(
    repo: EdgeRepository, output_root: Path, *, media_count: int = 1
) -> InspectionRecord:
    record = _record(NOW - timedelta(days=3), business=BusinessResult.OK, barcode="SN-E2D")
    record.media = [
        MediaMetadata(
            media_id=uuid4(),
            kind="KEY_FRAME",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path=f"{record.inspection_id}/frame-{i}.jpg",
            mime_type="image/jpeg",
            size_bytes=0,
            checksum_sha256="0" * 64,
        )
        for i in range(media_count)
    ]
    for item in record.media:
        _write_media_file(output_root, record, item)
    repo.persist_inspection_and_enqueue_uploads(record, retention=POLICY)
    _mark_synced(repo, record)
    return record


class TestIntegrityScan:
    def test_intact_media_produces_no_faults(self, repo: EdgeRepository, tmp_path: Path) -> None:
        output_root = tmp_path / "out"
        record = _seed_media(repo, output_root, media_count=2)
        report = scan_storage_integrity(repo, output_root)
        assert report.checked == 2
        assert report.faults == 0
        assert str(record.inspection_id) != ""

    def test_missing_file_is_faulted_and_protected(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        output_root = tmp_path / "out"
        record = _seed_media(repo, output_root)
        (output_root / record.media[0].relative_path).unlink()

        report = scan_storage_integrity(repo, output_root)
        assert report.faults == 1
        assert report.fault_codes["MEDIA_EVIDENCE_MISSING"] == 1
        # The faulted artifact is never eligible for deletion.
        assert repo.retention_eligible(NOW.isoformat()) == []
        metrics = repo.retention_metrics(NOW.isoformat())
        assert metrics.integrity_fault_count == 1

    def test_size_mismatch_is_faulted(self, repo: EdgeRepository, tmp_path: Path) -> None:
        output_root = tmp_path / "out"
        record = _seed_media(repo, output_root)
        path = output_root / record.media[0].relative_path
        path.write_bytes(b"tampered-bytes-larger-than-declared")

        report = scan_storage_integrity(repo, output_root)
        assert report.fault_codes.get("MEDIA_SIZE_MISMATCH", 0) == 1
        assert report.faults == 1

    def test_checksum_mismatch_is_faulted_when_verified(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        output_root = tmp_path / "out"
        record = _seed_media(repo, output_root)
        path = output_root / record.media[0].relative_path
        original = path.read_bytes()
        path.write_bytes(original + b"X")  # same size is not guaranteed; rewrite
        data = b"same-length-content"
        record.media[0].size_bytes = len(data)
        path.write_bytes(data)
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text("UPDATE media SET size_bytes = :size WHERE media_id = :id"),
                {"size": len(data), "id": str(record.media[0].media_id)},
            )

        without_checksum = scan_storage_integrity(repo, output_root, verify_checksums=False)
        assert without_checksum.faults == 0  # size matches, checksum not verified
        with_checksum = scan_storage_integrity(repo, output_root, verify_checksums=True)
        assert with_checksum.fault_codes.get("MEDIA_CHECKSUM_MISMATCH", 0) == 1

    def test_unsafe_path_is_faulted(self, repo: EdgeRepository, tmp_path: Path) -> None:
        output_root = tmp_path / "out"
        record = _seed_media(repo, output_root)
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text("UPDATE media SET relative_path = '../escape.jpg' WHERE inspection_id = :id"),
                {"id": str(record.inspection_id)},
            )
        report = scan_storage_integrity(repo, output_root)
        assert report.fault_codes.get("MEDIA_PATH_UNSAFE", 0) == 1

    def test_purged_tombstones_are_not_rescanned(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        output_root = tmp_path / "out"
        record = _seed_media(repo, output_root)
        media_id = str(record.media[0].media_id)
        (output_root / record.media[0].relative_path).unlink()
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text(
                    "UPDATE media SET lifecycle = 'PURGED', purged_at = :now WHERE media_id = :id"
                ),
                {"now": NOW.isoformat(), "id": media_id},
            )
        report = scan_storage_integrity(repo, output_root)
        assert report.checked == 0
        assert report.faults == 0


class TestQuarantine:
    def test_invalid_bundle_is_quarantined(self, repo: EdgeRepository, tmp_path: Path) -> None:
        output_root = tmp_path / "out"
        output_root.mkdir()
        bad = output_root / "bad-id"
        bad.mkdir()
        bad.joinpath("inspection.json").write_text("{not json", encoding="utf-8")

        assert reconcile_output_root(repo, output_root) == 0
        assert not bad.exists()
        assert (output_root / "quarantine" / "bad-id" / "inspection.json").is_file()

    def test_conflicting_bundle_is_quarantined(self, repo: EdgeRepository, tmp_path: Path) -> None:

        output_root = tmp_path / "out"
        output_root.mkdir()
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-CONF")
        directory = output_root / str(record.inspection_id)
        directory.mkdir()
        directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
        assert reconcile_output_root(repo, output_root) == 1

        conflicting = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-CONF")
        conflicting.inspection_id = record.inspection_id
        directory.joinpath("inspection.json").write_text(conflicting.model_dump_json(indent=2))
        assert reconcile_output_root(repo, output_root) == 0
        assert not directory.exists()
        fetched = repo.get_inspection_full(str(record.inspection_id))
        assert fetched is not None
        assert fetched.decision.business_result is BusinessResult.OK

    def test_quarantine_is_not_reimported(self, repo: EdgeRepository, tmp_path: Path) -> None:
        output_root = tmp_path / "out"
        output_root.mkdir()
        bad = output_root / "bad-id"
        bad.mkdir()
        bad.joinpath("inspection.json").write_text("{not json", encoding="utf-8")
        reconcile_output_root(repo, output_root)
        # A second startup does not re-import quarantined evidence.
        assert reconcile_output_root(repo, output_root) == 0


class TestDatabaseIntegrity:
    def test_corrupt_database_fails_closed(self, tmp_path: Path) -> None:
        db = tmp_path / "edge.sqlite3"
        repo = EdgeRepository.open(db)
        repo.close()
        # Zero the SQLite header after close: reopening must fail closed and
        # never serve a database that cannot be verified (design 12.8).
        with db.open("r+b") as handle:
            handle.seek(0)
            handle.write(b"\x00" * 100)
        with pytest.raises((RuntimeError, sqlite3.Error, Exception)):
            EdgeRepository.open(db)


class TestClaimRecovery:
    def test_startup_recovers_abandoned_claims(self, repo: EdgeRepository, tmp_path: Path) -> None:
        output_root = tmp_path / "out"
        record = _seed_media(repo, output_root)
        claimed = repo.claim_retention_batch(10, 1, (NOW - timedelta(minutes=5)).isoformat())
        assert len(claimed) == 1
        released = repo.recover_expired_retention_claims(NOW.isoformat())
        assert released == 1
        again = repo.claim_retention_batch(10, 120, NOW.isoformat())
        assert len(again) == 1
        assert str(record.inspection_id) != ""
