"""Camera frame source protocol and captured-frame types (design 07.3).

Vendor code is isolated behind the :class:`FrameSource` protocol so recorded
or simulated sources exercise the exact same downstream pipeline as a live
camera (ADR-013). Read/decode failures raise :class:`FrameStreamError`; they
are never silently skipped as absent evidence (fail-safe).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import Protocol, runtime_checkable

from assemblyvision_domain.errors import AssemblyVisionError
from PIL import Image


class FrameStreamError(AssemblyVisionError):
    """Raised when a frame source cannot open, read, or decode input."""


@dataclass(frozen=True, eq=False)
class CapturedFrame:
    """One acquired frame with acquisition metadata (design 07.3).

    ``width``/``height`` are derived from the image so they can never
    disagree with the buffer the pipeline consumes.
    """

    monotonic_ts_ns: int
    wall_clock_utc: datetime
    sequence: int
    pixel_format: str
    status: str
    image: Image.Image
    product_identity: str | None = None
    multi_product: bool = False

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height


@dataclass(frozen=True)
class CameraCapabilities:
    """What a source can deliver after ``open()`` (design 07.3)."""

    source_width: int
    source_height: int
    fps: float | None
    pixel_format: str


@dataclass(frozen=True)
class CameraSettings:
    """Requested capture settings; ``None`` leaves a value at source default."""

    fps: float | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class AppliedSettings:
    """The settings actually applied after ``configure()``."""

    fps: float | None
    width: int
    height: int


@runtime_checkable
class FrameSource(Protocol):
    """Vendor-neutral camera/frame input (design 07.3, ADR-013)."""

    def open(self) -> CameraCapabilities: ...

    def configure(self, settings: CameraSettings) -> AppliedSettings: ...

    def frames(self, stop: Event) -> Iterator[CapturedFrame]: ...

    def close(self) -> None: ...
