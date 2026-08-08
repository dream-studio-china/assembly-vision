"""Tests for the video file frame source (design 07.3, ADR-013)."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import cv2
import numpy as np
import pytest
from assemblyvision_vision.sources.frame_source import CameraSettings, FrameStreamError
from assemblyvision_vision.sources.video_source import VideoFrameSource
from PIL import Image


def _make_video(tmp_path: Path, count: int = 4, size: tuple[int, int] = (64, 48)) -> Path:
    path = tmp_path / "sample.avi"
    # "MJPG" as a raw fourcc int; cv2.VideoWriter_fourcc is missing from the
    # shipped OpenCV stubs.
    fourcc = ord("M") | (ord("J") << 8) | (ord("P") << 16) | (ord("G") << 24)
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, size)
    for i in range(count):
        frame = np.zeros((size[1], size[0], 3), np.uint8)
        frame[:, :, 0] = (i * 40) % 256
        writer.write(frame)
    writer.release()
    assert path.is_file()
    return path


def test_video_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FrameStreamError, match="does not exist"):
        VideoFrameSource(tmp_path / "missing.avi")


def test_video_frames_decode_in_order(tmp_path: Path) -> None:
    source = VideoFrameSource(_make_video(tmp_path, count=4))
    stop = Event()
    frames = list(source.frames(stop))
    assert [frame.sequence for frame in frames] == [1, 2, 3, 4]
    assert all(frame.width == 64 and frame.height == 48 for frame in frames)
    assert all(isinstance(frame.image, Image.Image) for frame in frames)
    stamps = [frame.monotonic_ts_ns for frame in frames]
    assert stamps == sorted(stamps)


def test_video_open_reports_capabilities(tmp_path: Path) -> None:
    source = VideoFrameSource(_make_video(tmp_path, count=2))
    capabilities = source.open()
    assert capabilities.source_width == 64
    assert capabilities.source_height == 48
    assert capabilities.fps is not None


def test_video_configure_overrides_fps(tmp_path: Path) -> None:
    source = VideoFrameSource(_make_video(tmp_path, count=2))
    applied = source.configure(CameraSettings(fps=5.0))
    assert applied.fps == 5.0
    assert applied.width == 64


def test_video_loop_respects_stop(tmp_path: Path) -> None:
    source = VideoFrameSource(_make_video(tmp_path, count=2), loop=True)
    stop = Event()
    iterator = source.frames(stop)
    first = next(iterator)
    second = next(iterator)
    assert first.sequence == 1 and second.sequence == 2
    # The loop rewinds to the first frame of the file.
    assert next(iterator).sequence == 3
    stop.set()
    with pytest.raises(StopIteration):
        next(iterator)
