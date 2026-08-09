"""Hardware-agnostic trigger/barcode/identity seam (E4b, design 07.4).

A :class:`TriggerSource` yields deterministic product-identity events; an
:class:`IdentityCorrelator` stamps each captured frame with the current
validated identity so the identity-sealed product-window boundary (PR-015 F1)
can group by physical product. Mock sources are development/test-only and are
gated behind explicit configuration so they can never masquerade as production
hardware (E4 task invariants 5-7). The time-only window fallback remains a
development mode.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from assemblyvision_vision.sources.frame_source import CapturedFrame


@dataclass(frozen=True)
class TriggerEvent:
    """One product-identity boundary on the frame stream.

    ``frame_offset`` is the frame index at which this identity becomes current
    and ``frames`` is how many frames it stays current, so a non-looping
    stream's end can expire the identity (frames after it have no identity and
    fail the identity-sealed window closed). ``barcode`` is carried as
    correlation metadata for the future hardware barcode source (E6), not
    injected into frames today.
    """

    identity: str
    frame_offset: int
    frames: int
    barcode: str | None = None


class TriggerSource(Protocol):
    """Yields product-identity boundary events in frame order."""

    def events(self) -> Iterator[TriggerEvent]: ...


@dataclass(frozen=True)
class MockProductSpec:
    """One mock product occupying ``frames`` frames of the trigger stream."""

    identity: str
    frames: int = 5
    barcode: str | None = None

    def __post_init__(self) -> None:
        if not self.identity:
            raise ValueError("mock product identity must be non-empty")
        if self.frames < 1:
            raise ValueError("mock product frames must be at least 1")


class MockTriggerSource:
    """Deterministic per-frame identity sequence for development and tests.

    With ``loop=True`` (default) the product list repeats forever; with
    ``loop=False`` the stream ends and frames after the last product have no
    identity, which exercises the fail-closed identity-missing path.
    """

    def __init__(self, products: Sequence[MockProductSpec], *, loop: bool = True) -> None:
        if not products:
            raise ValueError("at least one mock product is required")
        self._products = list(products)
        self._loop = loop

    def events(self) -> Iterator[TriggerEvent]:
        offset = 0
        while True:
            for product in self._products:
                yield TriggerEvent(
                    identity=product.identity,
                    barcode=product.barcode,
                    frame_offset=offset,
                    frames=product.frames,
                )
                offset += product.frames
            if not self._loop:
                return


class IdentityCorrelator:
    """Stamps captured frames with the current validated identity (E4b).

    The correlator advances through the trigger stream as frames are
    annotated; frames before the first boundary or after the end of a
    non-looping stream keep no identity so the window manager fails them
    closed rather than guessing a product (PR-015 F1).
    """

    def __init__(self, source: TriggerSource) -> None:
        self._events = iter(source.events())
        self._current: TriggerEvent | None = None
        self._pending: TriggerEvent | None = next(self._events, None)
        self._frame_index = 0

    def annotate(self, frame: CapturedFrame) -> CapturedFrame:
        """Return ``frame`` stamped with the identity current at this frame."""
        frame_index = self._frame_index
        while self._pending is not None and self._pending.frame_offset <= frame_index:
            self._current = self._pending
            self._pending = next(self._events, None)
        self._frame_index += 1
        current = self._current
        if current is None:
            return frame
        if current.frame_offset <= frame_index < current.frame_offset + current.frames:
            return replace(frame, product_identity=current.identity)
        # The identity expired (non-looping stream ended); the frame keeps no
        # identity so the window manager fails it closed (PR-015 F1).
        return frame
