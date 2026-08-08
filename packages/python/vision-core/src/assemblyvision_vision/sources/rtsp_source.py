"""Remote RTSP stream frame source (design 07.3, ADR-013).

Reads an RTSP URL with PyAV, falling back to an OpenCV capture when PyAV is
unavailable, and reconnects with bounded exponential backoff on stream end or
error. Frames never silently skip evidence.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count
from threading import Event
from typing import Any, cast

from PIL import Image

from assemblyvision_vision.sources._av import get_av
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
class RTSPReconnectPolicy:
    """Bounded exponential backoff for RTSP reconnects (design 07.7)."""

    initial_delay_ms: int = 250
    maximum_delay_ms: int = 10000


class RTSPFrameSource:
    """Yields frames decoded from a remote RTSP stream, reconnecting on drop."""

    def __init__(
        self,
        url: str,
        *,
        fps: float | None = None,
        reconnect: RTSPReconnectPolicy | None = None,
    ) -> None:
        if not url.startswith("rtsp://") and not url.startswith("rtsps://"):
            raise FrameStreamError(f"invalid RTSP url: {url!r}")
        self._url = url
        self._fps = fps
        self._reconnect = reconnect or RTSPReconnectPolicy()
        self._sequence = count(1)

    def open(self) -> CameraCapabilities:
        backend, resource = self._open_once()
        try:
            if backend == "av":
                width, height = self._av_dimensions(resource)
            else:
                width, height = self._cv2_dimensions(resource)
            return CameraCapabilities(
                source_width=width,
                source_height=height,
                fps=self._fps,
                pixel_format="RGB",
            )
        finally:
            self._close_resource(backend, resource)

    def configure(self, settings: CameraSettings) -> AppliedSettings:
        if settings.fps is not None:
            self._fps = settings.fps
        capabilities = self.open()
        return AppliedSettings(
            fps=self._fps,
            width=capabilities.source_width,
            height=capabilities.source_height,
        )

    def frames(self, stop: Event) -> Iterator[CapturedFrame]:
        while not stop.is_set():
            backend, resource = self._open_retrying(stop)
            if resource is None:
                return
            try:
                if backend == "av":
                    for frame in self._av_read(resource, stop):
                        yield frame
                else:
                    for frame in self._cv2_read(resource, stop):
                        yield frame
            finally:
                self._close_resource(backend, resource)
            self._backoff(stop)

    def close(self) -> None:
        """No persistent handle; captures are opened per session."""

    # -- helpers -----------------------------------------------------------

    def _open_retrying(self, stop: Event) -> tuple[str, Any | None]:
        """Open the stream with bounded backoff; (backend, None) when stopped."""
        delay_ms = self._reconnect.initial_delay_ms
        while not stop.is_set():
            try:
                return self._open_once()
            except FrameStreamError:
                self._sleep_backoff(stop, delay_ms)
                delay_ms = min(delay_ms * 2, self._reconnect.maximum_delay_ms)
        return "none", None

    def _open_once(self) -> tuple[str, Any]:
        try:
            av = get_av()
        except FrameStreamError:
            pass
        else:
            try:
                container = av.open(self._url, timeout=5, options={"rtsp_transport": "tcp"})
            except FrameStreamError:
                raise
            except Exception as exc:
                raise FrameStreamError(f"cannot open rtsp stream {self._url}: {exc}") from exc
            if not container.streams.video:
                container.close()
                raise FrameStreamError(f"rtsp url has no video stream: {self._url}")
            return "av", container
        # OpenCV fallback (an RTSP url is a valid capture source).
        cv2 = get_cv2()
        try:
            capture = cv2.VideoCapture(self._url)
            if not capture.isOpened():
                capture.release()
                raise FrameStreamError(f"cannot open rtsp url: {self._url}")
        except FrameStreamError:
            raise
        except Exception as exc:
            raise FrameStreamError(f"cannot open rtsp url: {self._url}: {exc}") from exc
        return "cv2", capture

    def _av_read(self, container: Any, stop: Event) -> Iterator[CapturedFrame]:
        stream = container.streams.video[0]
        try:
            for av_frame in container.decode(stream):
                if stop.is_set():
                    return
                yield self._frame(self._av_to_image(av_frame))
                pace(stop, self._fps)
        except FrameStreamError:
            raise
        except Exception as exc:
            raise FrameStreamError(f"cannot decode rtsp stream {self._url}: {exc}") from exc

    def _av_to_image(self, av_frame: Any) -> Image.Image:
        try:
            return cast(Image.Image, av_frame.to_image())
        except FrameStreamError:
            raise
        except Exception as exc:
            raise FrameStreamError(f"cannot convert rtsp frame from {self._url}: {exc}") from exc

    def _cv2_read(self, capture: Any, stop: Event) -> Iterator[CapturedFrame]:
        while not stop.is_set():
            try:
                ok, bgr = capture.read()
            except Exception as exc:
                raise FrameStreamError(f"cannot read rtsp frame from {self._url}: {exc}") from exc
            if not ok or bgr is None:
                return
            yield self._frame(to_pil_rgb(bgr))
            pace(stop, self._fps)

    def _frame(self, image: Any) -> CapturedFrame:
        return CapturedFrame(
            monotonic_ts_ns=time.monotonic_ns(),
            wall_clock_utc=datetime.now(UTC),
            sequence=next(self._sequence),
            pixel_format="RGB",
            status="OK",
            image=image,
        )

    @staticmethod
    def _av_dimensions(container: Any) -> tuple[int, int]:
        try:
            video = container.streams.video[0]
            return int(video.width or 0), int(video.height or 0)
        except Exception as exc:
            raise FrameStreamError(f"cannot read rtsp stream dimensions: {exc}") from exc

    @staticmethod
    def _cv2_dimensions(capture: Any) -> tuple[int, int]:
        cv2 = get_cv2()
        return (
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
        )

    @staticmethod
    def _close_resource(backend: str, resource: Any) -> None:
        if backend == "av":
            resource.close()
        elif backend == "cv2":
            resource.release()

    def _backoff(self, stop: Event) -> None:
        self._sleep_backoff(stop, self._reconnect.initial_delay_ms)

    @staticmethod
    def _sleep_backoff(stop: Event, delay_ms: int) -> None:
        deadline = time.monotonic() + delay_ms / 1000.0
        while time.monotonic() < deadline and not stop.is_set():
            time.sleep(min(0.05, deadline - time.monotonic()))
