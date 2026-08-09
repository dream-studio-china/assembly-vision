"""Deterministic per-component temporal aggregation (design 10, ADR-010).

The aggregator converts frame-level observations collected inside one product
window into per-component ``AggregatedComponentEvidence`` for the rule engine.
It is independent of YOLO, the database, and FastAPI; it never emits
``PRESENT`` from invalid, duplicate, or mixed-window evidence, and it cannot
improve a component's state through frames that belong elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.models import AggregatedComponentEvidence

_ACCEPTED_STATES = ("PRESENT", "MISSING", "UNCERTAIN", "UNVERIFIABLE")


@dataclass(frozen=True)
class ComponentTemporalPolicy:
    """One component's positive-evidence policy (design 10.6/10.7)."""

    high_confidence: float
    medium_confidence: float
    medium_hits: int = 2
    require_adjacent_hits: bool = True
    max_frame_gap: int = 1

    def __post_init__(self) -> None:
        for name, value in (
            ("high_confidence", self.high_confidence),
            ("medium_confidence", self.medium_confidence),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")
        if self.medium_hits < 1:
            raise ValueError("medium_hits must be >= 1")
        if self.max_frame_gap < 0:
            raise ValueError("max_frame_gap must be >= 0")
        # Strict ordering keeps the high-vs-repeated-medium distinction real;
        # equality would collapse the two evidence paths (design 10.7).
        if self.medium_confidence >= self.high_confidence:
            raise ValueError("medium_confidence must be strictly less than high_confidence")


@dataclass(frozen=True)
class TemporalAggregationConfig:
    """Window-level temporal aggregation policy (design 10.7).

    ``window_strategy`` selects the product-boundary mechanism: ``"time"`` is a
    development fallback that only separates windows by capture-time gap;
    ``"identity"`` requires a validated per-frame product identity and seals
    each window to one product, aborting on missing/transitioning identities or
    confirmed multi-product frames (PR-015 F1). Production temporal inspection
    must use ``"identity"`` or another validated correlation mechanism.
    """

    minimum_valid_frames: int = 1
    maximum_window_ms: int = 2500
    reject_duplicate_frame_ids: bool = True
    window_strategy: Literal["time", "identity"] = "time"
    components: dict[str, ComponentTemporalPolicy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.minimum_valid_frames < 1:
            raise ValueError("minimum_valid_frames must be >= 1")
        if self.maximum_window_ms <= 0:
            raise ValueError("maximum_window_ms must be positive")

    def policy_for(self, component_code: str) -> ComponentTemporalPolicy | None:
        return self.components.get(component_code)


@dataclass(frozen=True)
class FrameDetection:
    """One per-component detection inside a window frame."""

    component_code: str
    confidence: float
    roi_area_ratio: float
    center: tuple[float, float]


@dataclass(frozen=True)
class FrameEvidence:
    """Frame-level input consumed by the aggregator.

    ``usable_opportunity`` is true when the frame passed the quality gate and
    component inference ran on a valid ROI; only those frames count toward
    ``minimum_valid_frames`` and may contribute detections. A frame that is
    unusable, has no product, or failed inference reduces opportunities and can
    only push a component toward ``UNCERTAIN`` or ``UNVERIFIABLE``.
    """

    frame_id: UUID
    sequence: int
    usable_opportunity: bool
    detections: list[FrameDetection] = field(default_factory=list)


class TemporalAggregator:
    """Stateless per-component evidence resolver (design 10.6)."""

    def __init__(self, config: TemporalAggregationConfig) -> None:
        self._config = config

    @property
    def config(self) -> TemporalAggregationConfig:
        return self._config

    def aggregate(
        self,
        frames: list[FrameEvidence],
        required_components: tuple[str, ...],
    ) -> dict[str, AggregatedComponentEvidence]:
        """Resolve one final evidence set for every required component."""
        valid: list[FrameEvidence] = []
        if self._config.reject_duplicate_frame_ids:
            seen: set[UUID] = set()
            for frame in frames:
                if frame.frame_id in seen:
                    continue
                seen.add(frame.frame_id)
                valid.append(frame)
        else:
            valid = list(frames)
        valid = [frame for frame in valid if frame.usable_opportunity]
        return {
            component: self._resolve_component(component, valid)
            for component in required_components
        }

    def _resolve_component(
        self, component_code: str, valid: list[FrameEvidence]
    ) -> AggregatedComponentEvidence:
        policy = self._config.policy_for(component_code)
        opportunities = len(valid)
        if opportunities < self._config.minimum_valid_frames:
            return AggregatedComponentEvidence(
                component_code=component_code,
                state="UNVERIFIABLE",
                best_confidence=None,
                usable_frame_count=opportunities,
                detection_count=0,
                supporting_frame_ids=[],
                policy_reason_codes=[rc.INSUFFICIENT_VALID_FRAMES],
            )
        if policy is None:
            # Fail closed: an enabled temporal inspection must carry a versioned
            # policy for every required component (PR-015 F6). Reaching here
            # means invalid configuration slipped past validation.
            return AggregatedComponentEvidence(
                component_code=component_code,
                state="UNVERIFIABLE",
                best_confidence=None,
                usable_frame_count=opportunities,
                detection_count=0,
                supporting_frame_ids=[],
                policy_reason_codes=[rc.COMPONENT_POLICY_MISSING],
            )

        hits: list[tuple[FrameEvidence, FrameDetection]] = []
        for frame in valid:
            for detection in frame.detections:
                if detection.component_code == component_code:
                    hits.append((frame, detection))
        if not hits:
            return AggregatedComponentEvidence(
                component_code=component_code,
                state="MISSING",
                best_confidence=None,
                usable_frame_count=opportunities,
                detection_count=0,
                supporting_frame_ids=self._valid_frame_ids(valid),
                policy_reason_codes=[rc.COMPONENT_MISSING],
            )

        best = max((detection.confidence for _frame, detection in hits), default=0.0)
        high = policy.high_confidence
        medium = policy.medium_confidence
        if any(detection.confidence >= high for _frame, detection in hits):
            return self._present(component_code, valid, hits, opportunities)

        medium_hits = [hit for hit in hits if hit[1].confidence >= medium]
        if self._medium_policy_satisfied(medium_hits, policy):
            return self._present(component_code, valid, hits, opportunities)

        return AggregatedComponentEvidence(
            component_code=component_code,
            state="UNCERTAIN",
            best_confidence=best,
            usable_frame_count=opportunities,
            detection_count=0,
            supporting_frame_ids=self._supporting_frame_ids(hits),
            policy_reason_codes=[rc.COMPONENT_UNCERTAIN],
        )

    def _medium_policy_satisfied(
        self,
        medium_hits: list[tuple[FrameEvidence, FrameDetection]],
        policy: ComponentTemporalPolicy | None,
    ) -> bool:
        if not medium_hits:
            return False
        distinct = {frame.sequence for frame, _detection in medium_hits}
        required_hits = policy.medium_hits if policy is not None else 2
        if len(distinct) < required_hits:
            return False
        if policy is not None and not policy.require_adjacent_hits:
            return True
        ordered = sorted(distinct)
        run = 1
        longest = 1
        gap = policy.max_frame_gap if policy is not None else 1
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current - previous <= gap:
                run += 1
                longest = max(longest, run)
            else:
                run = 1
        return longest >= required_hits

    def _present(
        self,
        component_code: str,
        valid: list[FrameEvidence],
        hits: list[tuple[FrameEvidence, FrameDetection]],
        opportunities: int,
    ) -> AggregatedComponentEvidence:
        best_confidence = max(detection.confidence for _frame, detection in hits)
        # Count-based rules use the maximum number of instances observed in any
        # single valid frame; instances split across frames do not satisfy an
        # exact expected_count without co-occurrence (documented limitation).
        by_frame: dict[UUID, int] = {}
        for frame, _detection in hits:
            by_frame[frame.frame_id] = by_frame.get(frame.frame_id, 0) + 1
        count_frame_id = max(
            by_frame,
            key=lambda frame_id: (
                by_frame[frame_id],
                self._frame_confidence(frame_id, hits),
            ),
        )
        detection_count = by_frame[count_frame_id]
        ratios = [
            detection.roi_area_ratio
            for frame, detection in hits
            if frame.frame_id == count_frame_id
        ]
        centers = [
            detection.center for frame, detection in hits if frame.frame_id == count_frame_id
        ]
        return AggregatedComponentEvidence(
            component_code=component_code,
            state="PRESENT",
            best_confidence=best_confidence,
            usable_frame_count=opportunities,
            detection_count=detection_count,
            adjacent_detection_run=self._adjacent_run(hits),
            supporting_frame_ids=self._supporting_frame_ids(hits),
            box_area_ratios=ratios,
            box_centers=centers,
        )

    @staticmethod
    def _frame_confidence(
        frame_id: UUID, hits: list[tuple[FrameEvidence, FrameDetection]]
    ) -> float:
        return max(
            (detection.confidence for frame, detection in hits if frame.frame_id == frame_id),
            default=0.0,
        )

    @staticmethod
    def _valid_frame_ids(valid: list[FrameEvidence]) -> list[UUID]:
        return [frame.frame_id for frame in valid]

    @staticmethod
    def _supporting_frame_ids(
        hits: list[tuple[FrameEvidence, FrameDetection]],
    ) -> list[UUID]:
        ordered = sorted(hits, key=lambda item: (item[0].sequence, item[0].frame_id))
        return list(dict.fromkeys(frame.frame_id for frame, _detection in ordered))

    def _adjacent_run(self, hits: list[tuple[FrameEvidence, FrameDetection]]) -> int:
        ordered = sorted({frame.sequence for frame, _detection in hits})
        if not ordered:
            return 0
        run = 1
        longest = 1
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current - previous <= 1:
                run += 1
                longest = max(longest, run)
            else:
                run = 1
        return longest


def validate_evidence_states(evidence: dict[str, AggregatedComponentEvidence]) -> None:
    """Guard against any evidence state outside the documented set."""
    for key, entry in evidence.items():
        if entry.state not in _ACCEPTED_STATES:
            raise ValueError(f"evidence for {key} has invalid state {entry.state!r}")
