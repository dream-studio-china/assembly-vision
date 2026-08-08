"""Tests for the per-instance camera source manager (ADR-013)."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from assemblyvision_edge.camera_manager import CameraSourceManager
from assemblyvision_vision.sources import _av
from assemblyvision_vision.sources.folder_source import FolderSource
from assemblyvision_vision.sources.frame_source import FrameSource
from assemblyvision_vision.sources.rtsp_source import RTSPFrameSource
from PIL import Image


def _make_folder(tmp_path: Path, name: str, count: int = 2) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    for i in range(count):
        Image.new("RGB", (64, 48), (i * 40, 128, 128)).save(folder / f"img_{i}.png")
    return folder


def _wait_for_frame(manager: CameraSourceManager, instance_id: str, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager.latest_frame(instance_id) is not None:
            return True
        time.sleep(0.02)
    return False


def test_manager_starts_and_stops_multiple_instances(tmp_path: Path) -> None:
    sources: dict[str, FrameSource] = {
        "line-1": FolderSource(_make_folder(tmp_path, "a"), loop=True, fps=100.0),
        "line-2": FolderSource(_make_folder(tmp_path, "b"), loop=True, fps=100.0),
    }
    manager = CameraSourceManager(sources)
    manager.start()
    try:
        assert _wait_for_frame(manager, "line-1")
        assert _wait_for_frame(manager, "line-2")
        first = manager.state("line-1")
        second = manager.state("line-2")
        assert first is not None and first.connected
        assert second is not None and second.connected
        frame = manager.latest_frame("line-1")
        assert frame is not None and frame.width == 64
    finally:
        manager.stop()
    stopped = manager.state("line-1")
    assert stopped is not None and stopped.connected is False


def test_manager_single_instance_failure_is_non_fatal(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "zz_corrupt.png").write_bytes(b"not an image")
    healthy = _make_folder(tmp_path, "healthy")
    sources: dict[str, FrameSource] = {
        "bad": FolderSource(broken),
        "good": FolderSource(healthy, loop=True, fps=100.0),
    }
    manager = CameraSourceManager(sources)
    manager.start()
    try:
        # The broken folder fails at open (corrupt first image) and is marked
        # unavailable, while the healthy instance keeps streaming.
        bad = manager.state("bad")
        assert bad is not None and bad.error_code == "CAMERA_UNAVAILABLE"
        assert _wait_for_frame(manager, "good")
        good = manager.state("good")
        assert good is not None and good.connected
    finally:
        manager.stop()


def test_manager_reports_stream_ended(tmp_path: Path) -> None:
    # A single-shot folder source ends its stream; the manager marks it ended.
    sources: dict[str, FrameSource] = {
        "cam": FolderSource(_make_folder(tmp_path, "one", count=1), loop=False)
    }
    manager = CameraSourceManager(sources)
    manager.start()
    try:
        assert _wait_for_frame(manager, "cam")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            state = manager.state("cam")
            if state is not None and state.error_code == "STREAM_ENDED":
                break
            time.sleep(0.02)
        ended = manager.state("cam")
        assert ended is not None and ended.error_code == "STREAM_ENDED"
    finally:
        manager.stop()


def test_manager_latest_frame_is_bounded_to_one(tmp_path: Path) -> None:
    # Loop keeps the thread alive; only the latest frame is retained.
    sources: dict[str, FrameSource] = {
        "cam": FolderSource(_make_folder(tmp_path, "loop", count=2), loop=True, fps=100.0)
    }
    manager = CameraSourceManager(sources)
    manager.start()
    try:
        assert _wait_for_frame(manager, "cam")
        time.sleep(0.05)
        frame = manager.latest_frame("cam")
        assert frame is not None and frame.sequence >= 2
        state = manager.state("cam")
        assert state is not None and state.last_frame_at is not None
    finally:
        manager.stop()


def test_manager_rtsp_open_failure_does_not_abort_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BoomAV:
        def open(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("ffmpeg could not open")

    monkeypatch.setattr(_av, "_av", BoomAV())
    healthy = _make_folder(tmp_path, "healthy")
    sources: dict[str, FrameSource] = {
        "rtsp": RTSPFrameSource("rtsp://host/stream"),
        "good": FolderSource(healthy, loop=True, fps=100.0),
    }
    manager = CameraSourceManager(sources)
    manager.start()  # must not raise on the failing instance
    try:
        bad = manager.state("rtsp")
        assert bad is not None and bad.error_code == "CAMERA_UNAVAILABLE"
        assert bad.connected is False
        assert _wait_for_frame(manager, "good")
        good = manager.state("good")
        assert good is not None and good.connected
    finally:
        manager.stop()


def test_manager_rtsp_decode_failure_marks_stream_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ExplodingContainer:
        streams = SimpleNamespace(video=[SimpleNamespace(width=640, height=480)])

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.closed = False

        def decode(self, stream: object) -> object:
            yield SimpleNamespace(to_image=lambda: Image.new("RGB", (64, 48)))
            raise RuntimeError("broken stream")

        def close(self) -> None:
            self.closed = True

    class BoomDecodeAV:
        def open(self, *args: object, **kwargs: object) -> ExplodingContainer:
            return ExplodingContainer()

    monkeypatch.setattr(_av, "_av", BoomDecodeAV())
    healthy = _make_folder(tmp_path, "healthy")
    sources: dict[str, FrameSource] = {
        "rtsp": RTSPFrameSource("rtsp://host/stream"),
        "good": FolderSource(healthy, loop=True, fps=100.0),
    }
    manager = CameraSourceManager(sources)
    manager.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            bad = manager.state("rtsp")
            if bad is not None and bad.error_code == "CAMERA_STREAM_ERROR":
                break
            time.sleep(0.02)
        bad = manager.state("rtsp")
        assert bad is not None
        assert bad.error_code == "CAMERA_STREAM_ERROR"
        assert bad.connected is False
        assert _wait_for_frame(manager, "good")
        good = manager.state("good")
        assert good is not None and good.connected
    finally:
        manager.stop()


def test_manager_inspection_queue_overflow_sets_degraded(tmp_path: Path) -> None:
    # Capture emits frames far faster than any consumer, so the bounded queue
    # saturates and overflow is recorded explicitly (no silent loss, F1).
    sources: dict[str, FrameSource] = {
        "cam": FolderSource(_make_folder(tmp_path, "loop", count=200), loop=True, fps=2000.0)
    }
    manager = CameraSourceManager(sources)
    manager.subscribe_inspection("cam", maxsize=2)
    manager.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            state = manager.state("cam")
            if state is not None and state.frames_dropped > 0:
                break
            time.sleep(0.02)
        state = manager.state("cam")
        assert state is not None
        assert state.frames_dropped > 0
        assert state.degraded is True
        assert state.connected
    finally:
        manager.stop()


def test_manager_inspection_queue_delivers_frames_in_order(tmp_path: Path) -> None:
    sources: dict[str, FrameSource] = {
        "cam": FolderSource(_make_folder(tmp_path, "seq", count=20), loop=True, fps=100.0)
    }
    manager = CameraSourceManager(sources)
    manager.subscribe_inspection("cam", maxsize=16)
    manager.start()
    try:
        seen: list[int] = []
        deadline = time.monotonic() + 5.0
        while len(seen) < 8 and time.monotonic() < deadline:
            frame = manager.next_frame("cam", timeout=0.5)
            if frame is not None:
                seen.append(frame.sequence)
        assert seen == [1, 2, 3, 4, 5, 6, 7, 8]
        state = manager.state("cam")
        assert state is not None and state.frames_dropped == 0
    finally:
        manager.stop()


def test_manager_drain_inspection_records_overflow(tmp_path: Path) -> None:
    sources: dict[str, FrameSource] = {
        "cam": FolderSource(_make_folder(tmp_path, "loop", count=50), loop=True, fps=1000.0)
    }
    manager = CameraSourceManager(sources)
    manager.subscribe_inspection("cam", maxsize=4)
    manager.start()
    try:
        assert _wait_for_frame(manager, "cam")
        time.sleep(0.05)
        dropped = manager.drain_inspection("cam")
        assert dropped > 0
        state = manager.state("cam")
        assert state is not None
        assert state.frames_dropped >= dropped
        assert state.degraded is True
    finally:
        manager.stop()
