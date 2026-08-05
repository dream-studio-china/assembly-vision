"""Tests for the folder image source."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_edge.domain.errors import ImageReadError
from assemblyvision_edge.sources.folder_source import FolderSource
from PIL import Image


def _write_image(path: Path, color: tuple[int, int, int] = (128, 128, 128)) -> None:
    Image.new("RGB", (16, 16), color).save(path)


def test_iter_paths_is_deterministic_and_sorted(tmp_path: Path) -> None:
    _write_image(tmp_path / "b.png")
    _write_image(tmp_path / "a.jpg")
    (tmp_path / "c.txt").write_text("not an image", encoding="utf-8")
    source = FolderSource(tmp_path)
    paths = list(source.iter_paths())
    assert [p.name for p in paths] == ["a.jpg", "b.png"]


def test_read_converts_to_rgb(tmp_path: Path) -> None:
    path = tmp_path / "gray.png"
    Image.new("L", (16, 16), 128).save(path)
    image = FolderSource(tmp_path).read(path)
    assert image.mode == "RGB"


def test_read_missing_file_raises(tmp_path: Path) -> None:
    source = FolderSource(tmp_path)
    with pytest.raises(ImageReadError):
        source.read(tmp_path / "missing.png")


def test_missing_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(ImageReadError):
        FolderSource(tmp_path / "does-not-exist")
