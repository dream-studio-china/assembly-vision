"""Product window grouping for temporal aggregation (design 10, ADR-010).

A ``ProductWindowManager`` groups captured frames into one physical product
window. Frames arriving after a window is closed are recorded as dropped and
never mutate its decision; duplicate frame IDs are ignored and counted; a
forced close on shutdown discards the partial window as interrupted NG rather
than reconstructing evidence from un-journaled memory (design 10.8).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from assemblyvision_domain.models import ComponentDetection, ProductDetection, ROIResult
from PIL import Image

from assemblyvision_edge.temporal.aggregator import (
    FrameDetection,
    FrameEvidence,
    TemporalAggregationConfig,
)

CloseReason = Literal["GAP", "MAX_DURATION", "INTERRUPTED"]


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
    close_reason: CloseReason = "GAP"
    interrupted: bool = False

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

    @property
    def config(self) -> TemporalAggregationConfig:
        return self._config

    @property
    def active_window(self) -> ProductWindow | None:
        return self._active

    def feed(self, observation: FrameObservation, now_monotonic: float) -> ProductWindow | None:
        """Add one frame; returns the window closed by this frame, if any."""
        active = self._active
        if active is None:
            self._open(observation, now_monotonic)
            return None
        if self._config.reject_duplicate_frame_ids and any(
            frame.frame_id == observation.frame_id for frame in active.frames
        ):
            active.duplicate_frame_ids += 1
            return None
        gap_ms = self._config.maximum_window_ms
        if now_monotonic - active.last_frame_at_monotonic >= gap_ms / 1000.0:
            closed = self._close("GAP")
            self._open(observation, now_monotonic)
            return closed
        if now_monotonic - active.started_at_monotonic >= gap_ms / 1000.0:
            closed = self._close("MAX_DURATION")
            self._open(observation, now_monotonic)
            return closed
        active.frames.append(observation)
        active.last_frame_at_monotonic = now_monotonic
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
        active.frames = []
        self._active = None
        return active

    def _open(self, observation: FrameObservation, now_monotonic: float) -> None:
        self._active = ProductWindow(
            inspection_id=self._window_id_factory(),
            device_id=self._device_id,
            started_at=self._wall_clock(),
            started_at_monotonic=now_monotonic,
            last_frame_at_monotonic=now_monotonic,
            frames=[observation],
        )

    def _close(self, reason: CloseReason) -> ProductWindow:
        active = self._active
        if active is None:
            raise RuntimeError("cannot close a window that is not active")
        active.close_reason = reason
        self._active = None
        return active
