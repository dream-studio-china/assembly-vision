"""End-to-end product-window temporal aggregation through the pipeline.

Builds a real InspectionPipeline with scripted detectors and verifies that a
window of frames resolves to exactly one per-component-temporal inspection
record (design 10, ADR-010), including fail-safe NG, interrupted, and
insufficient-evidence paths.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.models import (
    BoundingBox,
    ComponentDetection,
    FrameQuality,
    ProductDetection,
)
from assemblyvision_edge.config import load_pipeline_config, load_rule_definition
from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.pipeline import InspectionPipeline
from assemblyvision_edge.rules.rule_engine import RuleEngine
from assemblyvision_edge.temporal.aggregator import (
    ComponentTemporalPolicy,
    TemporalAggregationConfig,
)
from assemblyvision_edge.temporal.window_manager import ProductWindow, ProductWindowManager
from assemblyvision_vision.manifests import load_model_manifest
from assemblyvision_vision.roi.geometry import Box, apply_transform, inverse_transform
from assemblyvision_vision.roi.roi_engine import ROIEngine
from assemblyvision_vision.sources.frame_source import CapturedFrame
from PIL import Image

from tests.conftest import COMPONENT_MANIFEST, EXAMPLE_PIPELINE, EXAMPLE_RULE, PRODUCT_MANIFEST

_REQUIRED = ("component_a", "component_b", "manual")


class ProductDetector:
    def __init__(self, qualities: list[FrameQuality] | None = None) -> None:
        self._qualities = iter(qualities or [])
        self._last: FrameQuality | None = None

    def detect(self, frame: Image.Image, frame_id: UUID) -> object:
        quality = next(self._qualities, self._last)
        self._last = quality
        return _Outcome(
            selected=_product_detection(frame_id, frame.width, frame.height, quality=quality)
        )


class ScriptedComponentDetector:
    """Returns one observation list per call, bound to the frame/ROI geometry.

    Once the script is exhausted the last list is reused so a window-trigger
    frame can be fed after the intended frames without failing.
    """

    def __init__(self, per_frame: list[list[tuple[str, float]]], model_version_id: UUID) -> None:
        self._calls = iter(per_frame)
        self._last: list[tuple[str, float]] = []
        self._model_version_id = model_version_id

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: tuple[str, ...],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        codes = next(self._calls, self._last)
        if codes is not self._last:
            self._last = codes
        frame_width, frame_height = frame_size
        inverse = inverse_transform(transform)
        result: list[ComponentDetection] = []
        for index, (code, confidence) in enumerate(codes):
            roi_bbox = BoundingBox(
                x_min=10.0 + index * 10,
                y_min=10.0,
                x_max=50.0 + index * 10,
                y_max=40.0,
                image_width=roi.width,
                image_height=roi.height,
            )
            full = apply_transform(Box.from_bbox(roi_bbox), inverse).to_bbox(
                frame_width, frame_height
            )
            result.append(
                ComponentDetection(
                    frame_id=frame_id,
                    component_code=code,
                    confidence=confidence,
                    roi_bbox=roi_bbox,
                    full_frame_bbox=full,
                    model_version_id=self._model_version_id,
                )
            )
        return result


class _Outcome:
    def __init__(
        self, selected: ProductDetection | None = None, reason_code: str | None = None
    ) -> None:
        self.selected = selected
        self.reason_code = reason_code


def _product_detection(
    frame_id: UUID,
    width: int,
    height: int,
    quality: FrameQuality | None = None,
) -> ProductDetection:
    return ProductDetection(
        frame_id=frame_id,
        product_class="product",
        confidence=0.95,
        bbox=BoundingBox(
            x_min=100.0,
            y_min=80.0,
            x_max=700.0,
            y_max=520.0,
            image_width=width,
            image_height=height,
        ),
        model_version_id=load_model_manifest(PRODUCT_MANIFEST).model_version_id,
        quality=quality
        or FrameQuality(
            usable=True,
            blur_score=0.0,
            brightness_mean=128.0,
            saturation_fraction=0.5,
        ),
    )


def _usable_quality() -> FrameQuality:
    return FrameQuality(usable=True, blur_score=0.0, brightness_mean=128.0, saturation_fraction=0.5)


def _unusable_quality() -> FrameQuality:
    return FrameQuality(
        usable=False,
        blur_score=1.5,
        brightness_mean=60.0,
        saturation_fraction=0.05,
        reason_codes=["BLUR_EXCESSIVE"],
    )


def _temporal_config(
    minimum_valid_frames: int = 1, maximum_window_ms: int = 1000
) -> TemporalAggregationConfig:
    policy = ComponentTemporalPolicy(
        high_confidence=0.9, medium_confidence=0.7, medium_hits=2, max_frame_gap=1
    )
    return TemporalAggregationConfig(
        minimum_valid_frames=minimum_valid_frames,
        maximum_window_ms=maximum_window_ms,
        reject_duplicate_frame_ids=True,
        components=dict.fromkeys(_REQUIRED, policy),
    )


def _build_pipeline(
    per_frame: list[list[tuple[str, float]]],
    temporal_config: TemporalAggregationConfig,
    qualities: list[FrameQuality] | None = None,
    rule: object | None = None,
) -> InspectionPipeline:
    config = load_pipeline_config(EXAMPLE_PIPELINE)
    loaded_rule = load_rule_definition(EXAMPLE_RULE) if rule is None else rule
    component_manifest = load_model_manifest(COMPONENT_MANIFEST)
    return InspectionPipeline(
        product_detector=ProductDetector(qualities),  # type: ignore[arg-type]
        component_detector=ScriptedComponentDetector(
            per_frame, component_manifest.model_version_id
        ),  # type: ignore[arg-type]
        roi_engine=ROIEngine(config.roi),
        rule_engine=RuleEngine(),
        rule=loaded_rule,  # type: ignore[arg-type]
        product_manifest=load_model_manifest(PRODUCT_MANIFEST),
        component_manifest=component_manifest,
        config=config,
        device_id=uuid4(),
        temporal_config=temporal_config,
    )


def _frame(sequence: int, product_identity: str | None = None) -> CapturedFrame:
    return CapturedFrame(
        monotonic_ts_ns=time.monotonic_ns(),
        wall_clock_utc=datetime.now(UTC),
        sequence=sequence,
        pixel_format="RGB",
        status="OK",
        image=Image.new("RGB", (800, 600), "gray"),
        product_identity=product_identity,
    )


def _run_window(
    pipeline: InspectionPipeline,
    temporal_config: TemporalAggregationConfig,
    frame_count: int,
    start: float = 1000.0,
) -> tuple[ProductWindow, ProductWindowManager]:
    manager = ProductWindowManager(temporal_config, pipeline._device_id)
    for sequence in range(1, frame_count + 1):
        observation = pipeline.frame_observations(_frame(sequence))
        manager.feed(observation, start + (sequence - 1) * 0.1)
    # Trigger a normal GAP close with a frame arriving after the window; the
    # returned window carries the intended frames and the trigger frame opens a
    # fresh (ignored) window.
    trigger = pipeline.frame_observations(_frame(frame_count + 1))
    closed = manager.feed(trigger, start + frame_count * 0.1 + 1.1)
    assert closed is not None
    return closed, manager


_ALL_HIGH = [
    [("component_a", 0.95), ("component_b", 0.95), ("manual", 0.95)],
    [("component_a", 0.95), ("component_b", 0.95), ("manual", 0.95)],
    [("component_a", 0.95), ("component_b", 0.95), ("manual", 0.95)],
]


class TestTemporalRecord:
    def test_window_produces_single_ok_record(self) -> None:
        pipeline = _build_pipeline(_ALL_HIGH, _temporal_config())
        closed, _manager = _run_window(pipeline, _temporal_config(), 3)
        record = pipeline.inspect_window(closed)
        assert record.aggregation_policy_version == "per-component-temporal-v1"
        assert record.decision.business_result == "OK"
        assert record.decision.internal_decision == "OK"
        assert all(e.state == "PRESENT" for e in record.evidence)
        assert record.frame_quality_summary.usable_frame_count == 3
        assert record.evidence[0].supporting_frame_ids

    def test_missing_component_is_ng(self) -> None:
        frames = [
            [("component_a", 0.95), ("component_b", 0.95)],
            [("component_a", 0.95), ("component_b", 0.95)],
            [("component_a", 0.95), ("component_b", 0.95)],
        ]
        pipeline = _build_pipeline(frames, _temporal_config())
        closed, _ = _run_window(pipeline, _temporal_config(), 3)
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "NG"
        assert "manual" in record.decision.missing_components
        manual = next(e for e in record.evidence if e.component_code == "manual")
        assert manual.state == "MISSING"

    def test_medium_hits_establish_presence(self) -> None:
        frames = [
            [("component_a", 0.75), ("component_b", 0.75), ("manual", 0.75)],
            [("component_a", 0.72), ("component_b", 0.72), ("manual", 0.72)],
        ]
        pipeline = _build_pipeline(frames, _temporal_config())
        closed, _ = _run_window(pipeline, _temporal_config(), 2)
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "OK"
        assert all(e.state == "PRESENT" for e in record.evidence)

    def test_insufficient_valid_frames_is_ng(self) -> None:
        pipeline = _build_pipeline(_ALL_HIGH, _temporal_config(minimum_valid_frames=3))
        closed, _ = _run_window(pipeline, _temporal_config(minimum_valid_frames=3), 1)
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "NG"
        assert all(e.state == "UNVERIFIABLE" for e in record.evidence)
        assert all(rc.INSUFFICIENT_VALID_FRAMES in e.policy_reason_codes for e in record.evidence)
        assert any("COMPONENT_UNVERIFIABLE" in reason for reason in record.decision.reason_codes)

    def test_interrupted_window_is_ng(self) -> None:
        pipeline = _build_pipeline(_ALL_HIGH, _temporal_config())
        manager = ProductWindowManager(_temporal_config(), pipeline._device_id)
        for sequence in range(1, 3):
            observation = pipeline.frame_observations(_frame(sequence))
            manager.feed(observation, 1000.0 + (sequence - 1) * 0.1)
        closed = manager.force_close()
        assert closed is not None and closed.interrupted
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "NG"
        assert rc.INSPECTION_INTERRUPTED in record.decision.reason_codes
        assert all(e.state == "UNVERIFIABLE" for e in record.evidence)


class TestTemporalPersistence:
    def test_window_persists_representative_bundle(self, tmp_path: Path) -> None:
        pipeline = _build_pipeline(_ALL_HIGH, _temporal_config())
        closed, _ = _run_window(pipeline, _temporal_config(), 3)
        writer = OutputWriter(tmp_path)
        record = pipeline.inspect_window(closed, writer)
        bundle = tmp_path / str(record.inspection_id)
        assert (bundle / "inspection.json").exists()
        assert (bundle / "key_frame.jpg").exists()
        payload = (bundle / "inspection.json").read_text(encoding="utf-8")
        assert '"aggregation_policy_version": "per-component-temporal-v1"' in payload


class TestQualityGate:
    """PR-015 F4: quality-rejected frames never contribute evidence."""

    def test_unusable_frame_does_not_increment_usable_count(self) -> None:
        pipeline = _build_pipeline(
            _ALL_HIGH,
            _temporal_config(),
            qualities=[_usable_quality(), _usable_quality(), _unusable_quality()],
        )
        closed, _ = _run_window(pipeline, _temporal_config(), 3)
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "OK"
        assert record.frame_quality_summary.usable_frame_count == 2
        assert record.frame_quality_summary.rejected_frame_count == 1
        quality_reasons = [r.reason_code for r in record.frame_quality_summary.reasons]
        assert "BLUR_EXCESSIVE" in quality_reasons

    def test_too_few_usable_frames_is_unverifiable_ng(self) -> None:
        pipeline = _build_pipeline(
            _ALL_HIGH,
            _temporal_config(minimum_valid_frames=3),
            qualities=[_usable_quality(), _unusable_quality(), _unusable_quality()],
        )
        closed, _ = _run_window(pipeline, _temporal_config(minimum_valid_frames=3), 3)
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "NG"
        assert all(e.state == "UNVERIFIABLE" for e in record.evidence)


class TestFrameReasonsAreDiagnostic:
    """PR-015 F5: rejected frames cannot veto sufficient aggregated evidence."""

    def test_rejected_frame_reason_does_not_force_ng(self) -> None:
        pipeline = _build_pipeline(
            _ALL_HIGH,
            _temporal_config(),
            qualities=[_usable_quality(), _usable_quality(), _unusable_quality()],
        )
        closed, _ = _run_window(pipeline, _temporal_config(), 3)
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "OK"
        # The rejection is persisted as frame diagnostics only.
        quality_reasons = [r.reason_code for r in record.frame_quality_summary.reasons]
        assert "BLUR_EXCESSIVE" in quality_reasons
        assert "BLUR_EXCESSIVE" not in record.decision.reason_codes


def _identity_config() -> TemporalAggregationConfig:
    """Identity-sealed window config with policies for every required component."""
    return TemporalAggregationConfig(
        minimum_valid_frames=1,
        maximum_window_ms=1000,
        reject_duplicate_frame_ids=True,
        window_strategy="identity",
        components=dict.fromkeys(_REQUIRED, ComponentTemporalPolicy(0.9, 0.7)),
    )


class TestProductIsolation:
    """PR-015 F1: different products must never mix evidence into one OK."""

    def test_complementary_products_within_interval_never_ok(self) -> None:
        # Product A supplies only component_a; product B supplies the rest. Both
        # arrive inside one gap interval, so a time-only grouping would merge
        # them into one all-PRESENT OK. Identity grouping must keep them apart.
        frames = [
            [("component_a", 0.95)],
            [("component_a", 0.95)],
            [("component_b", 0.95), ("manual", 0.95)],
            [("component_b", 0.95), ("manual", 0.95)],
        ]
        pipeline = _build_pipeline(frames, _identity_config())
        manager = ProductWindowManager(_identity_config(), pipeline._device_id)
        base = 1000.0
        for index, sequence in enumerate(range(1, len(frames) + 1)):
            identity = "prod-a" if index < 2 else "prod-b"
            observation = pipeline.frame_observations(_frame(sequence, product_identity=identity))
            closed = manager.feed(observation, base + index * 0.1)
            if closed is not None:
                record = pipeline.inspect_window(closed)
                assert record.decision.business_result == "NG"
                assert rc.PRODUCT_IDENTITY_TRANSITION in record.decision.reason_codes
        closed = manager.force_close()
        if closed is not None:
            record = pipeline.inspect_window(closed)
            assert record.decision.business_result == "NG"

    def test_same_identity_complete_window_is_ok(self) -> None:
        pipeline = _build_pipeline(_ALL_HIGH, _identity_config())
        manager = ProductWindowManager(_identity_config(), pipeline._device_id)
        base = 1000.0
        for index, sequence in enumerate(range(1, 4)):
            observation = pipeline.frame_observations(_frame(sequence, product_identity="prod-a"))
            assert manager.feed(observation, base + index * 0.1) is None
        trigger = pipeline.frame_observations(_frame(4, product_identity="prod-a"))
        closed = manager.feed(trigger, base + 4 * 0.1 + 1.1)
        assert closed is not None
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "OK"
        assert all(e.state == "PRESENT" for e in record.evidence)

    def test_missing_identity_mid_window_aborts_as_ng(self) -> None:
        frames = [
            [("component_a", 0.95), ("component_b", 0.95), ("manual", 0.95)],
            [("component_a", 0.95), ("component_b", 0.95), ("manual", 0.95)],
        ]
        pipeline = _build_pipeline(frames, _identity_config())
        manager = ProductWindowManager(_identity_config(), pipeline._device_id)
        base = 1000.0
        manager.feed(pipeline.frame_observations(_frame(1, product_identity="prod-a")), base)
        closed = manager.feed(
            pipeline.frame_observations(_frame(2, product_identity=None)), base + 0.1
        )
        assert closed is not None
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "NG"
        assert rc.PRODUCT_IDENTITY_MISSING in record.decision.reason_codes


def _count_rule() -> object:
    """Rule requiring exactly two component_a instances per product."""
    from assemblyvision_edge.rules.rule_engine import ComponentRequirement, RuleDefinition

    return RuleDefinition(
        schema_version=1,
        rule_id="count-rule",
        rule_version=1,
        product_type="model_a",
        compatible_component_model_versions=["component-yolo-1.0.0"],
        barcode_required=False,
        required_components={"component_a": ComponentRequirement(expected_count=2)},
        mandatory_gates={
            "product_detected": True,
            "roi_valid": True,
            "minimum_valid_frames_met": True,
        },
    )


class TestCountEvidenceThreshold:
    """PR-015 F7: below-threshold detections cannot satisfy exact counts."""

    def test_low_confidence_box_cannot_satisfy_exact_count_rule(self) -> None:
        frames = [[("component_a", 0.95), ("component_a", 0.5)]]
        pipeline = _build_pipeline(frames, _temporal_config(), rule=_count_rule())
        closed, _ = _run_window(pipeline, _temporal_config(), 1)
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "NG"
        assert "COMPONENT_COUNT_INVALID:component_a" in record.decision.reason_codes
        evidence = next(e for e in record.evidence if e.component_code == "component_a")
        assert evidence.detection_count == 1

    def test_qualifying_boxes_satisfy_exact_count_rule(self) -> None:
        frames = [[("component_a", 0.95), ("component_a", 0.9)]]
        pipeline = _build_pipeline(frames, _temporal_config(), rule=_count_rule())
        closed, _ = _run_window(pipeline, _temporal_config(), 1)
        record = pipeline.inspect_window(closed)
        assert record.decision.business_result == "OK"
        assert record.decision.internal_decision == "OK"
        evidence = next(e for e in record.evidence if e.component_code == "component_a")
        assert evidence.detection_count == 2
