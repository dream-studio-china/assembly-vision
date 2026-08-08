"""Remote HTTP-image polling frame source (design 07.3, ADR-013).

Polls a remote JPEG/PNG URL at a configured interval and emits each fetched
image as a frame. Transient HTTP failures retry with bounded backoff (camera
like); an undecodable response body raises :class:`FrameStreamError`
(fail-safe).
"""

from __future__ import annotations

import io
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count
from threading import Event
from typing import Any

import httpx
from PIL import Image

from assemblyvision_vision.sources._pacing import pace
from assemblyvision_vision.sources.frame_source import (
    AppliedSettings,
    CameraCapabilities,
    CameraSettings,
    CapturedFrame,
    FrameStreamError,
)


@dataclass(frozen=True)
class HttpImageReconnectPolicy:
    """Bounded backoff for transient HTTP-image fetch failures."""

    initial_delay_ms: int = 250
    maximum_delay_ms: int = 10000


class HttpImageFetchError(FrameStreamError):
    """Raised for retryable HTTP/network transport failures during fetch.

    Distinguished from decode/content failures, which raise a plain
    :class:`FrameStreamError` and are never retried (PR-014 F4).
    """


class HttpImageSource:
    """Yields frames by polling a remote image URL."""

    def __init__(
        self,
        url: str,
        *,
        fps: float | None = None,
        timeout_seconds: float = 5.0,
        reconnect: HttpImageReconnectPolicy | None = None,
    ) -> None:
        if not (url.startswith("http://") or url.startswith("https://")):
            raise FrameStreamError(f"invalid http-image url: {url!r}")
        self._url = url
        self._fps = fps
        self._timeout = timeout_seconds
        self._reconnect = reconnect or HttpImageReconnectPolicy()
        self._sequence = count(1)

    def open(self) -> CameraCapabilities:
        image = self._fetch()
        return CameraCapabilities(
            source_width=image.width,
            source_height=image.height,
            fps=self._fps,
            pixel_format="RGB",
        )

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
        delay_ms = self._reconnect.initial_delay_ms
        while not stop.is_set():
            try:
                image = self._fetch()
            except HttpImageFetchError:
                # Transient transport failure: back off and retry, camera like.
                self._sleep_backoff(stop, delay_ms)
                delay_ms = min(delay_ms * 2, self._reconnect.maximum_delay_ms)
                continue
            delay_ms = self._reconnect.initial_delay_ms
            yield self._frame(image)
            pace(stop, self._fps)

    def close(self) -> None:
        """No persistent handle; HTTP connections are per request."""

    def _fetch(self) -> Image.Image:
        try:
            response = httpx.get(self._url, timeout=self._timeout, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HttpImageFetchError(f"cannot fetch image url {self._url}: {exc}") from exc
        try:
            with Image.open(io.BytesIO(response.content)) as handle:
                return handle.convert("RGB")
        except Exception as exc:
            raise FrameStreamError(f"cannot decode image from url {self._url}") from exc

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
    def _sleep_backoff(stop: Event, delay_ms: int) -> None:
        deadline = time.monotonic() + delay_ms / 1000.0
        while time.monotonic() < deadline and not stop.is_set():
            time.sleep(min(0.05, deadline - time.monotonic()))
