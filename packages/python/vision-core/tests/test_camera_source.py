"""Tests for the OpenCV camera device source (design 07.3, ADR-013).

No real camera is required: a fake OpenCV module drives the source, including
open-failure retry and reconnect-after-drop paths.
"""

from __future__ import annotations

from threading import Event

import numpy as np
import pytest
from assemblyvision_vision.sources import _opencv
from assemblyvision_vision.sources.camera_source import OpenCVCameraSource, ReconnectPolicy
from assemblyvision_vision.sources.frame_source import CameraSettings, FrameStreamError


class FakeVideoCapture:
    """Yields a bounded number of frames, then goes quiet (drop)."""

    instances = 0

    def __init__(self, device: object) -> None:
        type(self).instances += 1
        self.device = device
        self._opened = True
        self._reads = 0
        self.released = False

    def isOpened(self) -> bool:
        return self._opened

    def set(self, prop: int, value: object) -> bool:
        return True

    def get(self, prop: int) -> float:
        if prop == 3:
            return 640.0
        if prop == 4:
            return 480.0
        return 25.0

    def read(self) -> tuple[bool, object]:
        if not self._opened or self._reads >= 3:
            return False, None
        self._reads += 1
        return True, np.zeros((480, 640, 3), np.uint8)

    def release(self) -> None:
        self._opened = False
        self.released = True


class FakeOpenCV:
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_POS_FRAMES = 1
    COLOR_BGR2RGB = 4
    VideoCapture = FakeVideoCapture

    @staticmethod
    def cvtColor(src: object, code: int) -> object:
        return src


@pytest.fixture
def fake_cv2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_opencv, "_cv2", FakeOpenCV)


def test_camera_open_reports_capabilities(fake_cv2: None) -> None:
    source = OpenCVCameraSource(0)
    capabilities = source.open()
    assert capabilities.source_width == 640
    assert capabilities.source_height == 480


def test_camera_configure_applies_settings(fake_cv2: None) -> None:
    source = OpenCVCameraSource(0)
    applied = source.configure(CameraSettings(fps=15.0))
    assert applied.fps == 15.0
    assert applied.width == 640


def test_camera_frames_reconnect_after_drop(fake_cv2: None) -> None:
    source = OpenCVCameraSource(
        0, reconnect=ReconnectPolicy(initial_delay_ms=1, maximum_delay_ms=2)
    )
    stop = Event()
    iterator = source.frames(stop)
    first = next(iterator)
    assert first.sequence == 1
    assert first.width == 640
    # Consume the three-frame batch; the drop triggers a reconnect.
    next(iterator)
    next(iterator)
    reconnected = next(iterator)
    assert reconnected.sequence == 4
    assert FakeVideoCapture.instances >= 2
    stop.set()
    with pytest.raises(StopIteration):
        next(iterator)


def test_camera_retries_open_failure_then_succeeds(
    fake_cv2: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FlakyCapture(FakeVideoCapture):
        attempts = 0

        def __init__(self, device: object) -> None:
            super().__init__(device)
            type(self).attempts += 1
            if type(self).attempts == 1:
                self._opened = False

    monkeypatch.setattr(FakeOpenCV, "VideoCapture", FlakyCapture)
    source = OpenCVCameraSource(
        0, reconnect=ReconnectPolicy(initial_delay_ms=1, maximum_delay_ms=2)
    )
    stop = Event()
    iterator = source.frames(stop)
    frame = next(iterator)
    assert frame.sequence == 1
    assert FlakyCapture.attempts >= 2
    stop.set()


def test_camera_close_releases_capture(fake_cv2: None, monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[FakeVideoCapture] = []

    class Tracked(FakeVideoCapture):
        def __init__(self, device: object) -> None:
            super().__init__(device)
            created.append(self)

    monkeypatch.setattr(FakeOpenCV, "VideoCapture", Tracked)
    source = OpenCVCameraSource(0)
    stop = Event()
    iterator = source.frames(stop)
    next(iterator)
    source.close()
    assert created and created[-1].released
    stop.set()
    with pytest.raises(StopIteration):
        next(iterator)


def test_camera_open_failure_raises(fake_cv2: None, monkeypatch: pytest.MonkeyPatch) -> None:
    class DeadCapture(FakeVideoCapture):
        def __init__(self, device: object) -> None:
            super().__init__(device)
            self._opened = False

    monkeypatch.setattr(FakeOpenCV, "VideoCapture", DeadCapture)
    source = OpenCVCameraSource(
        0, reconnect=ReconnectPolicy(initial_delay_ms=1, maximum_delay_ms=2)
    )
    with pytest.raises(FrameStreamError, match="cannot open camera device"):
        source._open_capture()
