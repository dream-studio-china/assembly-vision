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
from assemblyvision_edge.persistence.repository import EdgeRepository
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


def test_media_path_is_safe_rejects_escapes(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.reconcile import media_path_is_safe

    root = tmp_path / "out"
    root.mkdir()
    assert media_path_is_safe(root, "inspection-1/key_frame.jpg")
    assert not media_path_is_safe(root, "../secret.txt")
    assert not media_path_is_safe(root, "/etc/hostname")
    assert not media_path_is_safe(root, "")
    assert not media_path_is_safe(root, "inspection-1/../../secret.txt")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    assert not media_path_is_safe(root, "link/secret.txt")


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
    assert not media_path_is_safe(root, "key.jpg")
