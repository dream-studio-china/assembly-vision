"""Tests for the folder FrameSource (design 07.3, ADR-013)."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest
from assemblyvision_vision.sources.folder_source import FolderSource
from assemblyvision_vision.sources.frame_source import (
    CameraSettings,
    FrameSource,
    FrameStreamError,
)
from PIL import Image

_EXTENSIONS = (".jpg", ".png", ".bmp")


def _make_folder(tmp_path: Path, count: int = 3, *, corrupt: bool = False) -> Path:
    folder = tmp_path / "images"
    folder.mkdir()
    for i in range(count):
        image = Image.new("RGB", (64 + i, 48 + i), (i * 30, 128, 128))
        image.save(folder / f"img_{i:02d}.png")
    if corrupt:
        (folder / "zz_broken.jpg").write_bytes(b"not an image")
    return folder


def test_folder_source_implements_frame_source_protocol(tmp_path: Path) -> None:
    source = FolderSource(_make_folder(tmp_path))
    assert isinstance(source, FrameSource)


def test_folder_frames_are_deterministic_and_ordered(tmp_path: Path) -> None:
    source = FolderSource(_make_folder(tmp_path, count=3))
    stop = Event()
    frames = list(source.frames(stop))
    assert [frame.sequence for frame in frames] == [1, 2, 3]
    assert [frame.width for frame in frames] == [64, 65, 66]
    assert all(frame.status == "OK" for frame in frames)
    # Timestamps are populated and monotonic (ns clock).
    stamps = [frame.monotonic_ts_ns for frame in frames]
    assert stamps == sorted(stamps)
    assert all(frame.wall_clock_utc.tzinfo is not None for frame in frames)


def test_folder_frames_single_pass_without_loop(tmp_path: Path) -> None:
    source = FolderSource(_make_folder(tmp_path, count=2), loop=False)
    stop = Event()
    assert len(list(source.frames(stop))) == 2
    # Each frames() call replays the folder like a fresh camera session;
    # loop=False only stops re-walking within one pass.
    assert len(list(source.frames(stop))) == 2


def test_folder_frames_loop_respects_stop(tmp_path: Path) -> None:
    source = FolderSource(_make_folder(tmp_path, count=2), loop=True)
    stop = Event()
    iterator = source.frames(stop)
    first = next(iterator)
    second = next(iterator)
    assert first.sequence == 1 and second.sequence == 2
    stop.set()
    with pytest.raises(StopIteration):
        next(iterator)


def test_folder_open_reports_first_image_capabilities(tmp_path: Path) -> None:
    source = FolderSource(_make_folder(tmp_path, count=1))
    capabilities = source.open()
    assert capabilities.source_width == 64
    assert capabilities.source_height == 48
    assert capabilities.pixel_format == "RGB"


def test_folder_configure_applies_fps(tmp_path: Path) -> None:
    source = FolderSource(_make_folder(tmp_path, count=1))
    applied = source.configure(CameraSettings(fps=10.0))
    assert applied.fps == 10.0
    assert applied.width == 64


def test_folder_corrupt_file_raises_frame_stream_error(tmp_path: Path) -> None:
    source = FolderSource(_make_folder(tmp_path, count=2, corrupt=True))
    stop = Event()
    iterator = source.frames(stop)
    # The corrupt file sorts last (zz_broken.jpg); the two valid frames decode
    # first, then the undecodable file fails the stream (fail-safe).
    next(iterator)
    next(iterator)
    with pytest.raises(FrameStreamError):
        next(iterator)


def test_folder_missing_directory_raises_frame_stream_error() -> None:
    with pytest.raises(FrameStreamError, match="does not exist"):
        FolderSource(Path("/nonexistent/images"))
