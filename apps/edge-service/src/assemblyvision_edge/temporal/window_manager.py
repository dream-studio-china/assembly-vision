"""Product window grouping for temporal aggregation (design 10, ADR-010).

A ``ProductWindowManager`` groups captured frames into one physical product
window. Membership and duration are compared on the frame capture monotonic
clock, not on post-inference processing time, so queued or delayed frames keep
their acquisition-time boundaries. Frames arriving after a window is closed
are recorded as dropped and never mutate its decision; duplicate frame IDs and
stale out-of-order timestamps are ignored and counted; a forced close on
shutdown discards the partial window as interrupted NG rather than
reconstructing evidence from un-journaled memory (design 10.8).

With ``window_strategy == "identity"`` each frame must carry a validated
product identity (tracker, trigger, or barcode correlation). Windows are
sealed to one identity: a frame without an identity, a mid-window identity
transition, or a confirmed multi-product frame closes the active window as a
window-integrity violation that can never release ``OK`` (PR-015 F1). The
time-only strategy remains a development fallback; it does not prove that two
adjacent products cannot overlap.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.models import ComponentDetection, ProductDetection, ROIResult
from PIL import Image

from assemblyvision_edge.temporal.aggregator import (
    FrameDetection,
    FrameEvidence,
    TemporalAggregationConfig,
)

CloseReason = Literal[
    "GAP", "MAX_DURATION", "INTERRUPTED", "IDENTITY_MISSING", "IDENTITY_TRANSITION", "MULTI_PRODUCT"
]


@dataclass(frozen=True)
class FrameObservation:
    """One captured frame reduced to deterministic inspection observations."""

    frame_id: UUID
    sequence: int
    captured_at: datetime
    quality_usable: bool
    product_detected: bool
    roi_valid: bool
    inference_valid: bool
    product_detection: ProductDetection | None
    roi_result: ROIResult | None
    observations: list[ComponentDetection]
    reasons: list[str] = field(default_factory=list)
    product_latency_ms: float | None = None
    component_latency_ms: float | None = None
    image: Image.Image | None = None
    roi_image: Image.Image | None = None
    product_identity: str | None = None
    multi_product: bool = False

    def to_frame_evidence(self) -> FrameEvidence:
        """Convert this frame into aggregator input with spatial summaries."""
        detections = [
            FrameDetection(
                component_code=obs.component_code,
                confidence=obs.confidence,
                roi_area_ratio=obs.roi_bbox.area
                / (obs.roi_bbox.image_width * obs.roi_bbox.image_height),
                center=(
                    (obs.roi_bbox.x_min + obs.roi_bbox.x_max) / 2 / obs.roi_bbox.image_width,
                    (obs.roi_bbox.y_min + obs.roi_bbox.y_max) / 2 / obs.roi_bbox.image_height,
                ),
            )
            for obs in self.observations
        ]
        return FrameEvidence(
            frame_id=self.frame_id,
            sequence=self.sequence,
            usable_opportunity=self.quality_usable and self.inference_valid,
            detections=detections,
        )


@dataclass
class ProductWindow:
    """One physical-product inspection window."""

    inspection_id: UUID
    device_id: UUID
    started_at: datetime
    started_at_monotonic: float
    last_frame_at_monotonic: float
    frames: list[FrameObservation] = field(default_factory=list)
    duplicate_frame_ids: int = 0
    stale_frame_ids: int = 0
    identity: str | None = None
    close_reason: CloseReason = "GAP"
    interrupted: bool = False
    integrity_reason_codes: list[str] = field(default_factory=list)

    def frame_evidence_list(self) -> list[FrameEvidence]:
        """Aggregator input for all accepted frames, in capture order."""
        return [frame.to_frame_evidence() for frame in self.frames]


class ProductWindowManager:
    """Owns the active window for one instance and closes completed windows."""

    def __init__(
        self,
        config: TemporalAggregationConfig,
        device_id: UUID,
        *,
        window_id_factory: Callable[[], UUID] = uuid4,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._device_id = device_id
        self._window_id_factory = window_id_factory
        self._wall_clock = wall_clock
        self._active: ProductWindow | None = None
        self._latest_capture_monotonic: float | None = None
        self._closed_capture_cutoff: float | None = None
        self._stale_frame_count = 0

    @property
    def config(self) -> TemporalAggregationConfig:
        return self._config

    @property
    def active_window(self) -> ProductWindow | None:
        return self._active

    @property
    def stale_frame_count(self) -> int:
        """Number of stale frames dropped across completed and active windows."""
        return self._stale_frame_count

    def feed(self, observation: FrameObservation, now_monotonic: float) -> ProductWindow | None:
        """Add one frame; returns the window closed by this frame, if any.

        ``now_monotonic`` must be the frame's capture time on the monotonic
        clock (seconds); using post-inference processing time would let queue
        backlog or slow inference shift product boundaries.
        """
        stale_cutoff = (
            max(
                value
                for value in (self._latest_capture_monotonic, self._closed_capture_cutoff)
                if value is not None
            )
            if self._latest_capture_monotonic is not None or self._closed_capture_cutoff is not None
            else None
        )
        if stale_cutoff is not None and now_monotonic < stale_cutoff:
            # Keep the watermark after a window closes too. Otherwise a queued
            # pre-expiry frame could arrive late, open a new window, and form a
            # decision after the product was already finalized (PR-015 F3).
            self._stale_frame_count += 1
            if self._active is not None:
                self._active.stale_frame_ids += 1
            return None
        self._latest_capture_monotonic = now_monotonic
        if observation.multi_product:
            # A confirmed multi-product frame makes any active window
            # ambiguous and aborts it (design 10.8, PR-015 F1).
            active = self._active
            if active is None:
                return None
            return self._close_integrity("MULTI_PRODUCT", rc.MULTIPLE_PRODUCTS)
        if self._config.window_strategy == "identity":
            return self._feed_identity(observation, now_monotonic)
        return self._feed_active(observation, now_monotonic)

    def _feed_identity(
        self, observation: FrameObservation, now_monotonic: float
    ) -> ProductWindow | None:
        """Enforce one validated product identity per window (PR-015 F1)."""
        active = self._active
        identity = observation.product_identity
        if active is None:
            if identity is None:
                # No boundary signal and nothing open: drop the frame; there is
                # no product to decide.
                return None
            self._open(observation, now_monotonic, identity)
            return None
        if identity is None:
            # A frame without identity while a window is open cannot be proven
            # to belong to that product; abort the window fail-closed.
            return self._close_integrity("IDENTITY_MISSING", rc.PRODUCT_IDENTITY_MISSING)
        if identity != active.identity:
            closed = self._close_integrity("IDENTITY_TRANSITION", rc.PRODUCT_IDENTITY_TRANSITION)
            self._open(observation, now_monotonic, identity)
            return closed
        return self._feed_active(observation, now_monotonic)

    def _feed_active(
        self, observation: FrameObservation, now_monotonic: float
    ) -> ProductWindow | None:
        """Membership and duration checks for a continuing window."""
        active = self._active
        if active is None:
            self._open(observation, now_monotonic, observation.product_identity)
            return None
        if self._config.reject_duplicate_frame_ids and any(
            frame.frame_id == observation.frame_id for frame in active.frames
        ):
            active.duplicate_frame_ids += 1
            return None
        gap_ms = self._config.maximum_window_ms
        if now_monotonic - active.last_frame_at_monotonic >= gap_ms / 1000.0:
            closed = self._close("GAP")
            self._open(observation, now_monotonic, observation.product_identity)
            return closed
        if now_monotonic - active.started_at_monotonic >= gap_ms / 1000.0:
            closed = self._close("MAX_DURATION")
            self._open(observation, now_monotonic, observation.product_identity)
            return closed
        active.frames.append(observation)
        active.last_frame_at_monotonic = now_monotonic
        return None

    def expire(self, now_monotonic: float) -> ProductWindow | None:
        """Close the active window as ``GAP`` once its idle duration elapses.

        The runtime calls this on an empty capture poll so a final product at
        the end of a stream is finalized normally instead of waiting for a
        later trigger frame or for process shutdown (design 10.8). ``now`` is
        the runtime monotonic clock, which shares CLOCK_MONOTONIC with the
        capture timestamps stored on the window.
        """
        active = self._active
        if active is None:
            return None
        gap_ms = self._config.maximum_window_ms
        if now_monotonic - active.last_frame_at_monotonic >= gap_ms / 1000.0:
            self._closed_capture_cutoff = active.last_frame_at_monotonic + gap_ms / 1000.0
            return self._close("GAP")
        return None

    def force_close(self) -> ProductWindow | None:
        """Close the active window as interrupted NG (design 10.8).

        Partial in-memory evidence is discarded rather than reconstructed, so
        the closed window carries no frames and ``interrupted`` is set.
        """
        active = self._active
        if active is None:
            return None
        active.close_reason = "INTERRUPTED"
        active.interrupted = True
        active.integrity_reason_codes.append(rc.INSPECTION_INTERRUPTED)
        active.frames = []
        self._active = None
        return active

    def _open(
        self, observation: FrameObservation, now_monotonic: float, identity: str | None = None
    ) -> None:
        self._active = ProductWindow(
            inspection_id=self._window_id_factory(),
            device_id=self._device_id,
            started_at=self._wall_clock(),
            started_at_monotonic=now_monotonic,
            last_frame_at_monotonic=now_monotonic,
            identity=identity,
            frames=[observation],
        )

    def _close(self, reason: CloseReason) -> ProductWindow:
        active = self._active
        if active is None:
            raise RuntimeError("cannot close a window that is not active")
        active.close_reason = reason
        self._active = None
        return active

    def _close_integrity(self, reason: CloseReason, code: str) -> ProductWindow:
        """Close the active window as a fail-closed integrity violation."""
        active = self._active
        if active is None:
            raise RuntimeError("cannot close a window that is not active")
        active.close_reason = reason
        active.integrity_reason_codes.append(code)
        self._active = None
        return active
