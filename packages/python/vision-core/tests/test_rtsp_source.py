"""Tests for the RTSP frame source (design 07.3, ADR-013).

A fake PyAV module drives the source; the OpenCV fallback path is covered by
swapping in a fake OpenCV module, so no RTSP endpoint is needed in CI.
"""

from __future__ import annotations

from collections.abc import Iterator
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from assemblyvision_vision.sources import _av, _opencv
from assemblyvision_vision.sources.frame_source import CameraSettings, FrameStreamError
from assemblyvision_vision.sources.rtsp_source import RTSPFrameSource, RTSPReconnectPolicy
from PIL import Image


def _image() -> Image.Image:
    return Image.fromarray(np.zeros((480, 640, 3), np.uint8))


class FakeStream:
    width = 640
    height = 480


class FakeContainer:
    def __init__(
        self,
        url: str,
        timeout: int | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.options = options
        self.closed = False
        self.streams = SimpleNamespace(video=[FakeStream()])

    def decode(self, stream: object) -> Iterator[SimpleNamespace]:
        for _ in range(2):
            yield SimpleNamespace(to_image=_image)

    def close(self) -> None:
        self.closed = True


class FakeAV:
    containers: list[FakeContainer] = []

    def open(
        self, url: str, timeout: int | None = None, options: dict[str, object] | None = None
    ) -> FakeContainer:
        container = FakeContainer(url, timeout, options)
        type(self).containers.append(container)
        return container


@pytest.fixture
def fake_av(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_av, "_av", FakeAV())


def test_rtsp_invalid_url_raises() -> None:
    with pytest.raises(FrameStreamError, match="invalid RTSP url"):
        RTSPFrameSource("ftp://host/stream")


def test_rtsp_open_reports_capabilities(fake_av: None) -> None:
    source = RTSPFrameSource("rtsp://host/stream")
    capabilities = source.open()
    assert capabilities.source_width == 640
    assert capabilities.source_height == 480


def test_rtsp_configure_applies_fps(fake_av: None) -> None:
    source = RTSPFrameSource("rtsp://host/stream")
    applied = source.configure(CameraSettings(fps=12.0))
    assert applied.fps == 12.0
    assert applied.width == 640


def test_rtsp_frames_reconnect_after_stream_end(fake_av: None) -> None:
    source = RTSPFrameSource(
        "rtsp://host/stream", reconnect=RTSPReconnectPolicy(initial_delay_ms=1, maximum_delay_ms=2)
    )
    stop = Event()
    iterator = source.frames(stop)
    first = next(iterator)
    second = next(iterator)
    assert first.sequence == 1 and second.sequence == 2
    # The two-frame decode ends; the source reconnects and keeps streaming.
    reconnected = next(iterator)
    assert reconnected.sequence == 3
    assert len(FakeAV.containers) >= 2
    assert FakeAV.containers[0].closed
    stop.set()
    with pytest.raises(StopIteration):
        next(iterator)


def test_rtsp_falls_back_to_opencv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeVideoCapture:
        instances = 0

        def __init__(self, device: object) -> None:
            type(self).instances += 1
            self._reads = 0

        def isOpened(self) -> bool:
            return True

        def get(self, prop: int) -> float:
            return 640.0 if prop == 3 else 480.0

        def read(self) -> tuple[bool, object]:
            if self._reads >= 2:
                return False, None
            self._reads += 1
            return True, np.zeros((480, 640, 3), np.uint8)

        def release(self) -> None:
            return

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

    def no_av() -> object:
        raise FrameStreamError("PyAV is required for RTSP frame sources")

    import assemblyvision_vision.sources.rtsp_source as rtsp_source

    monkeypatch.setattr(rtsp_source, "get_av", no_av)
    monkeypatch.setattr(_opencv, "_cv2", FakeOpenCV)
    source = RTSPFrameSource(
        "rtsp://host/stream", reconnect=RTSPReconnectPolicy(initial_delay_ms=1, maximum_delay_ms=2)
    )
    stop = Event()
    iterator = source.frames(stop)
    first = next(iterator)
    assert first.sequence == 1
    assert first.width == 640
    assert FakeVideoCapture.instances >= 1
    stop.set()
    with pytest.raises(StopIteration):
        next(iterator)
