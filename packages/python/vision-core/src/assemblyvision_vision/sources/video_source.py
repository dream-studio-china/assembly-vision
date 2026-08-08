"""Local video file frame source (design 07.3, ADR-013).

Decodes a video file with OpenCV and emits frames at the configured rate,
optionally looping. A missing file or an undecodable frame raises
:class:`FrameStreamError` (fail-safe).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
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


class VideoFrameSource:
    """Yields frames decoded from a local video file."""

    def __init__(self, path: Path, *, fps: float | None = None, loop: bool = False) -> None:
        if not path.is_file():
            raise FrameStreamError(f"video file does not exist: {path}")
        self._path = path
        self._fps = fps
        self._loop = loop
        self._sequence = count(1)
        self._capture: Any | None = None

    def _open_capture(self) -> Any:
        cv2 = get_cv2()
        capture = cv2.VideoCapture(str(self._path))
        if not capture.isOpened():
            capture.release()
            raise FrameStreamError(f"cannot open video file: {self._path}")
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
        capabilities = self.open()
        return AppliedSettings(
            fps=self._fps,
            width=settings.width or capabilities.source_width,
            height=settings.height or capabilities.source_height,
        )

    def frames(self, stop: Event) -> Iterator[CapturedFrame]:
        cv2 = get_cv2()
        capture = self._open_capture()
        try:
            while not stop.is_set():
                ok, bgr = capture.read()
                if not ok or bgr is None:
                    if self._loop:
                        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    return
                yield self._frame(bgr)
                pace(stop, self._fps)
        finally:
            capture.release()

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
