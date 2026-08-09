"""Tests for the deterministic temporal aggregator (design 10, contract 03/06).

Covers the contract 06.5 required temporal aggregation cases, the design 10.10
table tests, and the fail-safe property tests: adding invalid evidence can
never turn a component PRESENT, and evidence for one component can never change
another.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.models import AggregatedComponentEvidence
from assemblyvision_edge.temporal.aggregator import (
    ComponentTemporalPolicy,
    FrameDetection,
    FrameEvidence,
    TemporalAggregationConfig,
    TemporalAggregator,
)

_REQUIRED = ("component_a",)


def _det(
    code: str, confidence: float, ratio: float = 0.5, center: tuple[float, float] = (0.5, 0.5)
) -> FrameDetection:
    return FrameDetection(
        component_code=code, confidence=confidence, roi_area_ratio=ratio, center=center
    )


def _frame(
    sequence: int,
    *,
    opportunity: bool = True,
    detections: list[FrameDetection] | None = None,
    frame_id: UUID | None = None,
) -> FrameEvidence:
    return FrameEvidence(
        frame_id=frame_id or uuid4(),
        sequence=sequence,
        usable_opportunity=opportunity,
        detections=detections or [],
    )


def _config(
    *,
    minimum_valid_frames: int = 1,
    high: float = 0.9,
    medium: float = 0.7,
    hits: int = 2,
    adjacent: bool = True,
    gap: int = 1,
    reject_duplicates: bool = True,
) -> TemporalAggregationConfig:
    return TemporalAggregationConfig(
        minimum_valid_frames=minimum_valid_frames,
        maximum_window_ms=2500,
        reject_duplicate_frame_ids=reject_duplicates,
        components={
            "component_a": ComponentTemporalPolicy(
                high_confidence=high,
                medium_confidence=medium,
                medium_hits=hits,
                require_adjacent_hits=adjacent,
                max_frame_gap=gap,
            )
        },
    )


def _aggregate(
    frames: list[FrameEvidence], config: TemporalAggregationConfig
) -> dict[str, AggregatedComponentEvidence]:
    return TemporalAggregator(config).aggregate(frames, _REQUIRED)


def _state(frames: list[FrameEvidence], config: TemporalAggregationConfig) -> str:
    return str(_aggregate(frames, config)["component_a"].state)


class TestContractRequiredCases:
    """The eight contract 06.5 temporal aggregator cases."""

    def test_one_high_confidence_detection_is_present(self) -> None:
        frames = [_frame(1, detections=[_det("component_a", 0.95)])]
        assert _state(frames, _config()) == "PRESENT"

    def test_repeated_medium_confidence_detections_are_present(self) -> None:
        frames = [
            _frame(1, detections=[_det("component_a", 0.75)]),
            _frame(2, detections=[_det("component_a", 0.72)]),
        ]
        assert _state(frames, _config()) == "PRESENT"

    def test_single_low_confidence_detection_is_not_present(self) -> None:
        frames = [_frame(1, detections=[_det("component_a", 0.5)])]
        assert _state(frames, _config()) == "UNCERTAIN"

    def test_no_detections_across_frames_is_missing(self) -> None:
        frames = [_frame(1), _frame(2), _frame(3)]
        assert _state(frames, _config(minimum_valid_frames=2)) == "MISSING"

    def test_no_usable_frames_is_unverifiable(self) -> None:
        frames = [_frame(1, opportunity=False), _frame(2, opportunity=False)]
        assert _state(frames, _config(minimum_valid_frames=2)) == "UNVERIFIABLE"

    def test_adjacent_frame_requirement_rejects_distant_hits(self) -> None:
        frames = [
            _frame(1, detections=[_det("component_a", 0.75)]),
            _frame(9, detections=[_det("component_a", 0.75)]),
        ]
        assert _state(frames, _config(gap=1)) == "UNCERTAIN"

    def test_blurred_frames_do_not_contribute_evidence(self) -> None:
        frames = [
            _frame(1, detections=[_det("component_a", 0.95)]),
            _frame(2, opportunity=False, detections=[_det("component_a", 0.95)]),
        ]
        # Only one usable opportunity exists; the blurred frame's detection is
        # excluded, so presence cannot be established.
        assert _state(frames, _config(minimum_valid_frames=1)) == "PRESENT"
        assert _state(frames, _config(minimum_valid_frames=2)) == "UNVERIFIABLE"

    def test_mixed_component_evidence_is_isolated_per_component(self) -> None:
        shared = uuid4()
        config = _config()
        config = TemporalAggregationConfig(
            minimum_valid_frames=config.minimum_valid_frames,
            maximum_window_ms=config.maximum_window_ms,
            reject_duplicate_frame_ids=config.reject_duplicate_frame_ids,
            components={
                "component_a": config.components["component_a"],
                "component_b": ComponentTemporalPolicy(high_confidence=0.9, medium_confidence=0.7),
            },
        )
        frames = [
            _frame(
                1,
                detections=[_det("component_a", 0.95), _det("component_b", 0.95)],
                frame_id=shared,
            ),
        ]
        result = TemporalAggregator(config).aggregate(frames, ("component_a", "component_b"))
        assert result["component_a"].state == "PRESENT"
        assert result["component_b"].state == "PRESENT"
        # Removing component_b detections must not change component_a.
        frames_b_removed = [_frame(1, detections=[_det("component_a", 0.95)], frame_id=shared)]
        result_removed = TemporalAggregator(config).aggregate(
            frames_b_removed, ("component_a", "component_b")
        )
        assert result_removed["component_a"] == result["component_a"]


class TestTableCases:
    """Design 10.10 threshold and hit-pattern tables."""

    def test_threshold_equality_is_high_hit(self) -> None:
        frames = [_frame(1, detections=[_det("component_a", 0.9)])]
        assert _state(frames, _config(high=0.9)) == "PRESENT"

    def test_repeated_same_frame_hits_are_one_temporal_hit(self) -> None:
        frames = [
            _frame(
                1,
                detections=[_det("component_a", 0.75), _det("component_a", 0.74)],
            )
        ]
        assert _state(frames, _config(hits=2)) == "UNCERTAIN"

    def test_two_detections_in_one_frame_still_one_temporal_hit(self) -> None:
        frames = [
            _frame(1, detections=[_det("component_a", 0.72), _det("component_a", 0.71)]),
            _frame(2, detections=[_det("component_a", 0.7)]),
        ]
        assert _state(frames, _config(hits=2)) == "PRESENT"

    def test_adjacency_gap_of_one_accepts_consecutive_frames(self) -> None:
        frames = [
            _frame(1, detections=[_det("component_a", 0.75)]),
            _frame(2, detections=[_det("component_a", 0.75)]),
        ]
        assert _state(frames, _config(gap=1)) == "PRESENT"

    def test_adjacent_requirement_disabled_allows_any_gap(self) -> None:
        frames = [
            _frame(1, detections=[_det("component_a", 0.75)]),
            _frame(9, detections=[_det("component_a", 0.75)]),
        ]
        assert _state(frames, _config(adjacent=False)) == "PRESENT"

    def test_no_hits_is_missing(self) -> None:
        frames = [_frame(1), _frame(2)]
        assert _state(frames, _config(minimum_valid_frames=2)) == "MISSING"

    def test_low_confidence_only_is_uncertain(self) -> None:
        frames = [
            _frame(1, detections=[_det("component_a", 0.5)]),
            _frame(2, detections=[_det("component_a", 0.49)]),
        ]
        assert _state(frames, _config(minimum_valid_frames=2)) == "UNCERTAIN"


class TestUnverifiableVsMissing:
    def test_insufficient_opportunities_is_unverifiable_even_with_hits(self) -> None:
        frames = [_frame(1, detections=[_det("component_a", 0.95)])]
        evidence = _aggregate(frames, _config(minimum_valid_frames=3))["component_a"]
        assert evidence.state == "UNVERIFIABLE"
        assert rc.INSUFFICIENT_VALID_FRAMES in evidence.policy_reason_codes
        assert evidence.best_confidence is None

    def test_sufficient_opportunities_without_hits_is_missing(self) -> None:
        frames = [_frame(1), _frame(2)]
        evidence = _aggregate(frames, _config(minimum_valid_frames=2))["component_a"]
        assert evidence.state == "MISSING"
        assert rc.COMPONENT_MISSING in evidence.policy_reason_codes

    def test_missing_policy_is_unverifiable_even_at_confidence_one(self) -> None:
        # PR-015 F6: without a configured, versioned policy a required
        # component must fail closed; an exact 1.0 detection must not PRESENT.
        frames = [_frame(1, detections=[_det("component_a", 1.0)])]
        config = TemporalAggregationConfig(
            minimum_valid_frames=1,
            maximum_window_ms=2500,
            reject_duplicate_frame_ids=True,
            components={},
        )
        evidence = _aggregate(frames, config)["component_a"]
        assert evidence.state == "UNVERIFIABLE"
        assert rc.COMPONENT_POLICY_MISSING in evidence.policy_reason_codes


class TestDuplicateHandling:
    def test_duplicate_frame_ids_ignored_by_default(self) -> None:
        shared = uuid4()
        frames = [
            _frame(1, detections=[_det("component_a", 0.75)], frame_id=shared),
            _frame(2, detections=[_det("component_a", 0.75)], frame_id=shared),
        ]
        # One distinct frame: medium_hits=2 is not satisfied.
        assert _state(frames, _config(hits=2)) == "UNCERTAIN"

    def test_duplicate_frame_ids_counted_when_not_rejected(self) -> None:
        shared = uuid4()
        frames = [
            _frame(1, detections=[_det("component_a", 0.75)], frame_id=shared),
            _frame(2, detections=[_det("component_a", 0.75)], frame_id=shared),
        ]
        assert _state(frames, _config(hits=2, reject_duplicates=False)) == "PRESENT"


class TestDetectionCountSemantics:
    def test_count_is_max_per_frame_for_present(self) -> None:
        frames = [
            _frame(1, detections=[_det("component_a", 0.95), _det("component_a", 0.9)]),
            _frame(2, detections=[_det("component_a", 0.93)]),
        ]
        evidence = _aggregate(frames, _config())["component_a"]
        assert evidence.state == "PRESENT"
        assert evidence.detection_count == 2

    def test_split_instances_do_not_raise_count(self) -> None:
        frames = [
            _frame(1, detections=[_det("component_a", 0.95)]),
            _frame(2, detections=[_det("component_a", 0.95)]),
        ]
        evidence = _aggregate(frames, _config())["component_a"]
        assert evidence.state == "PRESENT"
        assert evidence.detection_count == 1

    def test_present_evidence_records_supporting_frames_and_spatials(self) -> None:
        first = uuid4()
        second = uuid4()
        frames = [
            _frame(
                1,
                detections=[_det("component_a", 0.95, ratio=0.3, center=(0.2, 0.4))],
                frame_id=first,
            ),
            _frame(
                2,
                detections=[_det("component_a", 0.92, ratio=0.4, center=(0.6, 0.7))],
                frame_id=second,
            ),
        ]
        evidence = _aggregate(frames, _config())["component_a"]
        assert set(evidence.supporting_frame_ids) == {first, second}
        assert evidence.best_confidence == 0.95
        assert evidence.usable_frame_count == 2
        # The count frame is the one establishing detection_count: both frames
        # have one hit, so the tie resolves to the higher-confidence frame.
        assert evidence.box_area_ratios == [0.3]
        assert evidence.box_centers == [(0.2, 0.4)]


class TestFailSafeProperties:
    """Design 10.10 property tests."""

    def test_invalid_evidence_cannot_turn_component_present(self) -> None:
        baseline = [_frame(1, detections=[_det("component_a", 0.5)])]
        before = _aggregate(baseline, _config())["component_a"]
        poisoned = baseline + [_frame(2, opportunity=False, detections=[_det("component_a", 0.99)])]
        after = _aggregate(poisoned, _config())["component_a"]
        assert after.state != "PRESENT"
        assert after.state == before.state

    def test_duplicate_injected_evidence_cannot_turn_component_present(self) -> None:
        shared = uuid4()
        baseline = [_frame(1, detections=[_det("component_a", 0.75)], frame_id=shared)]
        injected = baseline + [_frame(2, detections=[_det("component_a", 0.75)], frame_id=shared)]
        assert _state(baseline, _config(hits=2)) == "UNCERTAIN"
        assert _state(injected, _config(hits=2)) == "UNCERTAIN"

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            ComponentTemporalPolicy(high_confidence=0.7, medium_confidence=0.9)
        with pytest.raises(ValueError):
            ComponentTemporalPolicy(high_confidence=0.7, medium_confidence=0.7)
        with pytest.raises(ValueError):
            TemporalAggregationConfig(minimum_valid_frames=0)
        with pytest.raises(ValueError):
            TemporalAggregationConfig(maximum_window_ms=0)
