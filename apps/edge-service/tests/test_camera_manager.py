"""Tests for the per-instance camera source manager (ADR-013)."""

from __future__ import annotations

import time
from pathlib import Path

from assemblyvision_edge.camera_manager import CameraSourceManager
from assemblyvision_vision.sources.folder_source import FolderSource
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
    sources = {
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
    sources = {
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
    sources = {"cam": FolderSource(_make_folder(tmp_path, "one", count=1), loop=False)}
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
    sources = {"cam": FolderSource(_make_folder(tmp_path, "loop", count=2), loop=True, fps=100.0)}
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
