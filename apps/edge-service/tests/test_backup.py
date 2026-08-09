"""E5c backup and restore tests (design 20.10).

Covers consistent snapshotting, pending-evidence preservation, bundle checksum
verification, tamper rejection, and restart-after-restore continuity.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_edge.backup import backup_edge, restore_edge
from assemblyvision_edge.persistence.repository import EdgeRepository

from tests.test_api import _record


def _pending_media_paths(repo: EdgeRepository, output: Path) -> list[Path]:
    """Return the on-disk paths of media whose upload task has not succeeded."""
    paths: list[Path] = []
    for task in repo.list_uploads(limit=200).items:
        if task.kind != "MEDIA" or task.status == "SUCCEEDED" or task.inspection_id is None:
            continue
        for media in repo.list_inspection_media(str(task.inspection_id)):
            if str(media.media_id) == str(task.object_id):
                paths.append(output / media.relative_path)
    return paths


def _seed_store(db_path: Path, output: Path) -> None:
    """Persist two inspections with real media files on disk."""
    from assemblyvision_domain.models import BusinessResult
    from assemblyvision_edge.output.writer import OutputWriter
    from PIL import Image

    writer = OutputWriter(output)
    repository = EdgeRepository.open(str(db_path))
    try:
        for business, barcode in ((BusinessResult.OK, "SN-up"), (BusinessResult.NG, "SN-pending")):
            record = _record(datetime.now(UTC), business=business, barcode=barcode)
            saved = writer.save(
                record,
                full_frame=Image.new("RGB", (40, 40), (30, 30, 30)),
                roi_image=None,
                annotated=None,
            )
            repository.persist_inspection_and_enqueue_uploads(saved)
    finally:
        repository.close()


def test_backup_restore_round_trip_preserves_pending_evidence(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    db_path = output / "edge.sqlite3"
    _seed_store(db_path, output)
    bundle = tmp_path / "backup.tar.gz"

    report = backup_edge(output_root=output, db_path=db_path, dest=bundle)
    assert report.bundle_path == bundle
    assert report.pending_media >= 1
    assert report.bundle_sha256

    # Restore into a fresh root; media and pending tasks come back.
    fresh = tmp_path / "restored"
    restored_db = fresh / "edge.sqlite3"
    restore = restore_edge(backup=bundle, output_root=fresh, db_path=restored_db)
    assert restore.restored_db is True
    assert restore.restored_media >= 1

    repository = EdgeRepository.open(str(restored_db))
    try:
        page = repository.list_inspections(limit=50)
        barcodes = {row.barcode for row in page.items}
        assert "SN-pending" in barcodes
        pending = [
            task
            for task in repository.list_uploads(limit=200).items
            if task.kind == "MEDIA" and task.status != "SUCCEEDED"
        ]
        assert pending
    finally:
        repository.close()


def test_backup_fails_closed_on_missing_pending_media(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    db_path = output / "edge.sqlite3"
    _seed_store(db_path, output)
    repository = EdgeRepository.open(str(db_path))
    try:
        pending = _pending_media_paths(repository, output)
        assert pending
        pending[0].unlink()
    finally:
        repository.close()
    with pytest.raises(ConfigError, match="pending media"):
        backup_edge(output_root=output, db_path=db_path, dest=tmp_path / "b.tar.gz")


def test_restore_rejects_tampered_bundle(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    db_path = output / "edge.sqlite3"
    _seed_store(db_path, output)
    bundle = tmp_path / "backup.tar.gz"
    backup_edge(output_root=output, db_path=db_path, dest=bundle)
    data = bytearray(bundle.read_bytes())
    data[len(data) // 2] ^= 0xFF
    tampered = tmp_path / "tampered.tar.gz"
    tampered.write_bytes(bytes(data))
    with pytest.raises(ConfigError, match="invalid|checksum"):
        restore_edge(backup=tampered, output_root=tmp_path / "fresh", db_path=tmp_path / "d.db")


def test_restore_never_overwrites_conflicting_media(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    db_path = output / "edge.sqlite3"
    _seed_store(db_path, output)
    bundle = tmp_path / "backup.tar.gz"
    backup_edge(output_root=output, db_path=db_path, dest=bundle)

    repository = EdgeRepository.open(str(db_path))
    try:
        pending = _pending_media_paths(repository, output)
        assert pending
    finally:
        repository.close()

    fresh = tmp_path / "restored"
    restored_db = fresh / "edge.sqlite3"
    relative = pending[0].relative_to(output)
    conflict = fresh / relative
    conflict.parent.mkdir(parents=True, exist_ok=True)
    conflict.write_bytes(b"conflicting-bytes")
    with pytest.raises(ConfigError, match="overwrite conflicting"):
        restore_edge(backup=bundle, output_root=fresh, db_path=restored_db)


def test_backup_snapshot_is_consistent_while_writing(tmp_path: Path) -> None:
    """The online backup API yields a consistent snapshot even mid-write."""
    output = tmp_path / "out"
    output.mkdir()
    db_path = output / "edge.sqlite3"
    # Open once so migrations create the full schema (media/upload_tasks).
    EdgeRepository.open(str(db_path)).close()
    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO t (value) VALUES ('a')")
        connection.commit()
        bundle = tmp_path / "b.tar.gz"
        # A concurrent writer leaves an uncommitted row visible only to itself.
        connection.execute("BEGIN")
        connection.execute("INSERT INTO t (value) VALUES ('uncommitted')")
        backup_edge(output_root=output, db_path=db_path, dest=bundle)
        connection.rollback()
    finally:
        connection.close()
    fresh = tmp_path / "fresh"
    restore_edge(backup=bundle, output_root=fresh, db_path=fresh / "edge.sqlite3")
    check = sqlite3.connect(str(fresh / "edge.sqlite3"))
    try:
        rows = check.execute("SELECT value FROM t").fetchall()
        assert rows == [("a",)]
    finally:
        check.close()
