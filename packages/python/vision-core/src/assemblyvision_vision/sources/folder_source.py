"""Folder image source with deterministic ordering (FrameSource protocol).

Implements the :class:`FrameSource` protocol (design 07.3, ADR-013) so a
directory of static images can simulate a camera stream, while preserving the
original ``iter_paths``/``read`` API used by the static-image MVP pipeline.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from threading import Event

from assemblyvision_domain.errors import ImageReadError
from PIL import Image

from assemblyvision_vision.sources.frame_source import (
    AppliedSettings,
    CameraCapabilities,
    CameraSettings,
    CapturedFrame,
    FrameStreamError,
)

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"})


class FolderSource:
    """Reads images from a directory in deterministic sorted order."""

    def __init__(self, folder: Path, *, loop: bool = False, fps: float | None = None) -> None:
        if not folder.is_dir():
            raise ImageReadError(f"input folder does not exist: {folder}")
        self._folder = folder
        self._loop = loop
        self._fps = fps
        self._sequence = count(1)

    @property
    def folder(self) -> Path:
        return self._folder

    def iter_paths(self) -> Iterator[Path]:
        """Yield supported image paths in deterministic sorted order."""
        for path in sorted(self._folder.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                yield path

    def read(self, path: Path) -> Image.Image:
        """Decode an image as RGB; raises ImageReadError on failure.

        Any decode failure maps to ImageReadError so the pipeline fails safe
        (NG); third-party PIL patches (e.g. Ultralytics HEIF) must not turn a
        corrupt image into an uncaught exception.
        """
        try:
            with Image.open(path) as handle:
                image: Image.Image = handle.convert("RGB")
                return image
        except Exception as exc:
            raise ImageReadError(f"cannot decode image: {path}") from exc

    # -- FrameSource protocol (design 07.3) ---------------------------------

    def open(self) -> CameraCapabilities:
        """Report capabilities from the first decodable image, if any."""
        for path in self.iter_paths():
            image = self.read(path)
            return CameraCapabilities(
                source_width=image.width,
                source_height=image.height,
                fps=self._fps,
                pixel_format="RGB",
            )
        return CameraCapabilities(
            source_width=0, source_height=0, fps=self._fps, pixel_format="RGB"
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
        """Yield one frame per image in deterministic order; loops when set.

        A decode failure raises :class:`FrameStreamError` instead of silently
        skipping the frame (fail-safe). ``fps`` paces emission between frames
        when configured.
        """
        while not stop.is_set():
            for path in self.iter_paths():
                if stop.is_set():
                    return
                yield self._frame(path)
                if self._loop:
                    self._pace(stop)
            if not self._loop:
                return

    def close(self) -> None:
        """Nothing to release for a folder source."""

    def _frame(self, path: Path) -> CapturedFrame:
        try:
            image = self.read(path)
        except ImageReadError as exc:
            raise FrameStreamError(f"cannot decode frame from folder: {path}: {exc}") from exc
        return CapturedFrame(
            monotonic_ts_ns=time.monotonic_ns(),
            wall_clock_utc=datetime.now(UTC),
            sequence=next(self._sequence),
            pixel_format="RGB",
            status="OK",
            image=image,
        )

    def _pace(self, stop: Event) -> None:
        """Sleep to the configured frame rate, aborting early on stop."""
        if not self._fps or self._fps <= 0:
            return
        delay = 1.0 / self._fps
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline and not stop.is_set():
            time.sleep(min(0.01, delay))
