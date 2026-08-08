"""OpenCV local/virtual camera device source (design 07.3, ADR-013).

Reads from a local camera index or device path (for example ``/dev/videoN``),
which includes virtual camera drivers such as Linux ``v4l2loopback`` or OBS
Virtual Camera. Reconnects with bounded exponential backoff and never silently
skips evidence.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count
from threading import Event
from typing import Any

from assemblyvision_vision.sources._opencv import get_cv2, to_pil_rgb
from assemblyvision_vision.sources._pacing import pace
from assemblyvision_vision.sources.frame_source import (
    AppliedSettings,
    CameraCapabilities,
    CameraSettings,
    CapturedFrame,
    FrameStreamError,
)


@dataclass(frozen=True)
class ReconnectPolicy:
    """Bounded exponential backoff for device reconnects (design 07.7)."""

    initial_delay_ms: int = 250
    maximum_delay_ms: int = 10000


class OpenCVCameraSource:
    """Yields frames from an OpenCV camera device, reconnecting on failure."""

    def __init__(
        self,
        device: int | str,
        *,
        fps: float | None = None,
        width: int | None = None,
        height: int | None = None,
        reconnect: ReconnectPolicy | None = None,
    ) -> None:
        self._device = device
        self._fps = fps
        self._width = width
        self._height = height
        self._reconnect = reconnect or ReconnectPolicy()
        self._sequence = count(1)
        self._capture: Any | None = None

    def _open_capture(self) -> Any:
        cv2 = get_cv2()
        capture = cv2.VideoCapture(self._device)
        if self._width is not None:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        if self._height is not None:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if not capture.isOpened():
            capture.release()
            raise FrameStreamError(f"cannot open camera device {self._device!r}")
        return capture

    def open(self) -> CameraCapabilities:
        cv2 = get_cv2()
        capture = self._open_capture()
        try:
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            source_fps = capture.get(cv2.CAP_PROP_FPS) or None
        finally:
            capture.release()
        return CameraCapabilities(
            source_width=width,
            source_height=height,
            fps=self._fps or source_fps,
            pixel_format="RGB",
        )

    def configure(self, settings: CameraSettings) -> AppliedSettings:
        if settings.fps is not None:
            self._fps = settings.fps
        if settings.width is not None:
            self._width = settings.width
        if settings.height is not None:
            self._height = settings.height
        capabilities = self.open()
        return AppliedSettings(
            fps=self._fps,
            width=capabilities.source_width,
            height=capabilities.source_height,
        )

    def frames(self, stop: Event) -> Iterator[CapturedFrame]:
        """Yield frames continuously, reconnecting on read failure or disconnect.

        The stream runs until ``stop`` is set; a disconnected device triggers
        bounded backoff instead of ending the stream.
        """
        while not stop.is_set():
            capture = self._open_retrying(stop)
            if capture is None:
                return
            try:
                while not stop.is_set():
                    ok, bgr = capture.read()
                    if not ok or bgr is None:
                        break
                    yield self._frame(bgr)
                    pace(stop, self._fps)
            finally:
                capture.release()
            self._backoff(stop)

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _frame(self, bgr: Any) -> CapturedFrame:
        return CapturedFrame(
            monotonic_ts_ns=time.monotonic_ns(),
            wall_clock_utc=datetime.now(UTC),
            sequence=next(self._sequence),
            pixel_format="RGB",
            status="OK",
            image=to_pil_rgb(bgr),
        )

    def _open_retrying(self, stop: Event) -> Any | None:
        """Open the device with bounded backoff; None when stopped."""
        delay_ms = self._reconnect.initial_delay_ms
        while not stop.is_set():
            try:
                capture = self._open_capture()
            except FrameStreamError:
                self._sleep_backoff(stop, delay_ms)
                delay_ms = min(delay_ms * 2, self._reconnect.maximum_delay_ms)
                continue
            self._capture = capture
            return capture
        return None

    def _backoff(self, stop: Event) -> None:
        """After a stream drop, wait before reconnecting."""
        self._sleep_backoff(stop, self._reconnect.initial_delay_ms)

    @staticmethod
    def _sleep_backoff(stop: Event, delay_ms: int) -> None:
        deadline = time.monotonic() + delay_ms / 1000.0
        while time.monotonic() < deadline and not stop.is_set():
            time.sleep(min(0.05, deadline - time.monotonic()))
