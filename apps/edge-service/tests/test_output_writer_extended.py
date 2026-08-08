"""Failure-path tests for the output writer and the reconcile importer."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.errors import OutputError
from assemblyvision_edge.output.writer import (
    OutputWriter,
    _fsync_dir,
    _fsync_path,
    _write_file_atomic,
)
from assemblyvision_edge.persistence.reconcile import reconcile_output_root
from assemblyvision_edge.persistence.repository import EdgeRepository, InspectionSummary, Page
from PIL import Image

from tests.test_output_writer import _make_record


def test_fsync_path_and_dir(tmp_path: Path) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"data")
    _fsync_path(target)
    _fsync_dir(tmp_path)
    assert target.read_bytes() == b"data"


def test_write_file_atomic_failure_raises_and_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    def broken_fsync(fd: int) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    with pytest.raises(OutputError):
        _write_file_atomic(tmp_path / "out.bin", b"x")
    assert not list(tmp_path.glob("*.tmp"))
    assert not (tmp_path / "out.bin").exists()


def test_save_failure_publishes_nothing_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    writer = OutputWriter(tmp_path / "out")
    record = _make_record(uuid4())

    def broken_fsync(fd: int) -> None:
        raise OSError("cannot fsync")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    with pytest.raises(OutputError):
        writer.save(record, full_frame=None, roi_image=None, annotated=None)
    assert not (tmp_path / "out" / str(record.inspection_id)).exists()
    assert not list((tmp_path / "out").glob(".staging-*"))


def test_save_image_encode_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = OutputWriter(tmp_path / "out")
    record = _make_record(uuid4())

    def broken_save(
        self: object, fp: object, format: str | None = None, quality: int | None = None
    ) -> None:  # noqa: A002
        raise OSError("cannot encode")

    monkeypatch.setattr(Image.Image, "save", broken_save)
    with pytest.raises(OutputError):
        writer.save(record, full_frame=Image.new("RGB", (16, 16)), roi_image=None, annotated=None)
    assert not (tmp_path / "out" / str(record.inspection_id)).exists()


def test_reconcile_missing_root_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, tmp_path / "no-such-root") == 0
    finally:
        repo.close()


def test_reconcile_skips_staging_and_invalid_json(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    staging = root / ".staging-deadbeef"
    staging.mkdir()
    staging.joinpath("inspection.json").write_text("{}", encoding="utf-8")
    (root / "corrupt-id").mkdir()
    (root / "corrupt-id" / "inspection.json").write_text("{not json", encoding="utf-8")

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 0
        assert repo.list_inspections().items == []
    finally:
        repo.close()


def test_reconcile_skips_already_imported(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    record = _make_record(uuid4())
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(
        record.model_dump_json(indent=2), encoding="utf-8"
    )

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 1
        # A second record with the same ID is skipped (already imported).
        assert reconcile_output_root(repo, root) == 0
    finally:
        repo.close()


def test_reconcile_skips_unsafe_media_paths(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    for _name, relative in (("traversal", "../secret.txt"), ("absolute", "/etc/hostname")):
        record = _make_record(uuid4())
        directory = root / str(record.inspection_id)
        directory.mkdir()
        payload = record.model_dump(mode="json")
        payload["media"] = [
            {
                "media_id": str(uuid4()),
                "kind": "KEY_FRAME",
                "lifecycle": "AVAILABLE",
                "relative_path": relative,
                "mime_type": "image/jpeg",
                "size_bytes": 4,
                "checksum_sha256": "0" * 64,
            }
        ]
        directory.joinpath("inspection.json").write_text(json.dumps(payload), encoding="utf-8")

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 0
        assert repo.list_inspections().items == []
    finally:
        repo.close()


def test_reconcile_skips_conflicting_content(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from assemblyvision_domain.models import BusinessResult

    from tests.test_api import _record

    root = tmp_path / "out"
    root.mkdir()
    record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-CONFLICT")
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 1
        conflicting = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-CONFLICT")
        conflicting.inspection_id = record.inspection_id
        directory.joinpath("inspection.json").write_text(conflicting.model_dump_json(indent=2))
        assert reconcile_output_root(repo, root) == 0
        fetched = repo.get_inspection_full(str(record.inspection_id))
        assert fetched is not None
        assert fetched.decision.business_result is BusinessResult.OK
    finally:
        repo.close()


def test_rebuild_index_from_cli_bundles_is_equivalent(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from assemblyvision_domain.models import BusinessResult

    from tests.test_api import _record

    root = tmp_path / "out"
    root.mkdir()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    records = []
    for idx in range(3):
        record = _record(
            base + timedelta(minutes=idx),
            business=BusinessResult.OK if idx % 2 == 0 else BusinessResult.NG,
            barcode=f"SN-{idx:04d}",
        )
        directory = root / str(record.inspection_id)
        directory.mkdir()
        directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
        records.append(record)

    db1 = tmp_path / "edge.sqlite3"
    repo1 = EdgeRepository.open(db1)
    assert reconcile_output_root(repo1, root) == 3
    snapshot1 = repo1.list_inspections(limit=100)
    detail1 = repo1.get_inspection_full(str(records[0].inspection_id))
    repo1.close()

    repo2 = EdgeRepository.open(tmp_path / "edge-rebuilt.sqlite3")
    assert reconcile_output_root(repo2, root) == 3
    snapshot2 = repo2.list_inspections(limit=100)
    detail2 = repo2.get_inspection_full(str(records[0].inspection_id))
    repo2.close()

    def key(page: Page[InspectionSummary]) -> list[tuple[str, str]]:
        return [(str(i.inspection_id), i.business_result) for i in page.items]

    assert key(snapshot1) == key(snapshot2)
    assert detail1 is not None and detail2 is not None
    assert detail1.model_dump(mode="json") == detail2.model_dump(mode="json")


def test_reconcile_skips_duplicate_media_paths(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from assemblyvision_domain.models import BusinessResult, MediaLifecycle, MediaMetadata

    from tests.test_api import _record

    root = tmp_path / "out"
    root.mkdir()
    record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-DUPM")
    record.media = [
        MediaMetadata(
            media_id=uuid4(),
            kind="KEY_FRAME",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path="key.jpg",
            mime_type="image/jpeg",
            size_bytes=1,
            checksum_sha256="0" * 64,
        ),
        MediaMetadata(
            media_id=uuid4(),
            kind="PRODUCT_ROI",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path="key.jpg",
            mime_type="image/jpeg",
            size_bytes=1,
            checksum_sha256="0" * 64,
        ),
    ]
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 0
        assert repo.list_inspections().items == []
    finally:
        repo.close()


def test_reconcile_quarantines_stale_staging(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    staging = root / ".staging-deadbeef-abc"
    staging.mkdir()
    staging.joinpath("inspection.json").write_text("{}", encoding="utf-8")

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 0
        assert not staging.exists()
        assert (root / "quarantine" / ".staging-deadbeef-abc" / "inspection.json").is_file()
        assert repo.list_inspections().items == []
    finally:
        repo.close()


def test_quarantine_missing_root_returns_zero(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.reconcile import quarantine_stale_staging

    assert quarantine_stale_staging(tmp_path / "no-such-root") == 0


def test_quarantine_skips_non_directory(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.reconcile import quarantine_stale_staging

    root = tmp_path / "out"
    root.mkdir()
    (root / ".staging-file").write_text("x", encoding="utf-8")
    assert quarantine_stale_staging(root) == 0
    assert (root / ".staging-file").is_file()
    assert not (root / "quarantine").exists()


def test_quarantine_handles_rename_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from assemblyvision_edge.persistence import reconcile as reconcile_mod

    root = tmp_path / "out"
    root.mkdir()
    staging = root / ".staging-x"
    staging.mkdir()

    def broken_rename(self: object, target: object) -> object:
        raise OSError("busy")

    monkeypatch.setattr(Path, "rename", broken_rename)
    assert reconcile_mod.quarantine_stale_staging(root) == 0
    assert staging.is_dir()


def test_reconcile_skips_staging_dir_when_quarantine_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.persistence import reconcile as reconcile_mod

    root = tmp_path / "out"
    root.mkdir()
    staging = root / ".staging-xyz"
    staging.mkdir()
    staging.joinpath("inspection.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(reconcile_mod, "quarantine_stale_staging", lambda output_root: 0)

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 0
        assert repo.list_inspections().items == []
    finally:
        repo.close()


def test_media_path_is_safe_rejects_escapes(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.reconcile import media_path_is_safe

    root = tmp_path / "out"
    root.mkdir()
    assert media_path_is_safe(root, "inspection-1", "inspection-1/key_frame.jpg")
    assert not media_path_is_safe(root, "inspection-1", "../secret.txt")
    assert not media_path_is_safe(root, "inspection-1", "/etc/hostname")
    assert not media_path_is_safe(root, "inspection-1", "")
    assert not media_path_is_safe(root, "inspection-1", "inspection-1/../../secret.txt")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    assert not media_path_is_safe(root, "inspection-1", "link/secret.txt")


def test_media_path_is_safe_oserror_is_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.persistence.reconcile import media_path_is_safe

    root = tmp_path / "out"
    root.mkdir()
    real_resolve = Path.resolve

    def boom(self: Path, strict: bool = False) -> Path:
        if "key.jpg" in str(self):
            raise OSError("cannot resolve")
        return real_resolve(self, strict)

    monkeypatch.setattr(Path, "resolve", boom)
    assert not media_path_is_safe(root, "inspection-1", "inspection-1/key.jpg")


def test_media_path_is_safe_rejects_nul_byte(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.reconcile import media_path_is_safe

    root = tmp_path / "out"
    root.mkdir()
    # An embedded NUL byte makes Path.resolve raise ValueError, not OSError.
    assert not media_path_is_safe(root, "inspection-1", "inspection-1/key\x00frame.jpg")


def test_reconcile_skips_nul_byte_media_without_aborting(tmp_path: Path) -> None:
    from assemblyvision_domain.models import MediaLifecycle, MediaMetadata
    from assemblyvision_edge.persistence.reconcile import reconcile_output_root

    root = tmp_path / "out"
    root.mkdir()

    valid = _make_record(uuid4())
    valid_dir = root / str(valid.inspection_id)
    valid_dir.mkdir()
    valid_dir.joinpath("inspection.json").write_text(valid.model_dump_json(indent=2))

    malformed = _make_record(uuid4())
    malformed.media = [
        MediaMetadata(
            media_id=uuid4(),
            kind="KEY_FRAME",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path=f"{malformed.inspection_id}/key\x00frame.jpg",
            mime_type="image/jpeg",
            size_bytes=1,
            checksum_sha256="0" * 64,
        )
    ]
    malformed_dir = root / str(malformed.inspection_id)
    malformed_dir.mkdir()
    malformed_dir.joinpath("inspection.json").write_text(malformed.model_dump_json(indent=2))

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 1
        assert repo.get_inspection(str(valid.inspection_id)) is not None
        assert repo.get_inspection(str(malformed.inspection_id)) is None
    finally:
        repo.close()
