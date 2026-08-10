"""Tests for pipeline orchestration and fail-safe behavior."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.errors import DetectionError, ROIGenerationError, RuleEvaluationError
from assemblyvision_domain.models import (
    BoundingBox,
    BusinessResult,
    ComponentDetection,
    FrameQuality,
    InspectionRecord,
    ProductDetection,
)
from assemblyvision_edge.barcode import BarcodeObservation, BarcodeSource, resolve_barcode_identity
from assemblyvision_edge.config import (
    BarcodeIdentityConfig,
    load_pipeline_config,
    load_rule_definition,
)
from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.pipeline import InspectionPipeline
from assemblyvision_edge.rules.rule_engine import RuleEngine
from assemblyvision_vision.manifests import load_model_manifest
from assemblyvision_vision.roi.roi_engine import ROIEngine
from assemblyvision_vision.sources.folder_source import FolderSource
from assemblyvision_vision.sources.frame_source import CapturedFrame
from PIL import Image

from tests.conftest import COMPONENT_MANIFEST, EXAMPLE_PIPELINE, EXAMPLE_RULE, PRODUCT_MANIFEST


class FakeProductDetector:
    """Returns a product detection bound to the frame and frame ID supplied."""

    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    def detect(self, frame: Image.Image, frame_id: UUID) -> object:
        outcome = self._outcome
        if isinstance(outcome, _Outcome) and outcome.selected is not None:
            outcome.selected = _product_detection(frame_id, frame.width, frame.height)
        return outcome


class RaisingProductDetector:
    def detect(self, frame: Image.Image, frame_id: UUID) -> object:
        raise DetectionError("INFERENCE_ERROR", "boom")


class StaleFrameProductDetector:
    """Returns a detection whose frame ID does not match the current frame."""

    def detect(self, frame: Image.Image, frame_id: UUID) -> object:
        return _Outcome(selected=_product_detection(uuid4(), frame.width, frame.height))


class FakeComponentDetector:
    """Returns observations bound to the supplied frame/ROI geometry."""

    def __init__(self, observations: list[ComponentDetection]) -> None:
        self._observations = observations

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: tuple[str, ...],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        from assemblyvision_vision.roi.geometry import Box, apply_transform, inverse_transform

        frame_width, frame_height = frame_size
        inverse = inverse_transform(transform)
        result: list[ComponentDetection] = []
        for obs in self._observations:
            roi_bbox = BoundingBox(
                x_min=obs.roi_bbox.x_min,
                y_min=obs.roi_bbox.y_min,
                x_max=obs.roi_bbox.x_max,
                y_max=obs.roi_bbox.y_max,
                image_width=roi.width,
                image_height=roi.height,
            )
            full = apply_transform(Box.from_bbox(roi_bbox), inverse).to_bbox(
                frame_width, frame_height
            )
            result.append(
                ComponentDetection(
                    frame_id=frame_id,
                    component_code=obs.component_code,
                    confidence=obs.confidence,
                    roi_bbox=roi_bbox,
                    full_frame_bbox=full,
                    model_version_id=obs.model_version_id,
                )
            )
        return result


class RaisingComponentDetector:
    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: tuple[str, ...],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        raise DetectionError("INFERENCE_ERROR", "component boom")


class _Outcome:
    def __init__(
        self, selected: ProductDetection | None = None, reason_code: str | None = None
    ) -> None:
        self.selected = selected
        self.reason_code = reason_code


class RaisingRuleEngine:
    def evaluate(self, context: object, rule: object) -> object:
        raise RuleEvaluationError("boom")


def _build_pipeline(
    product_detector: object,
    component_detector: object,
    rule_engine: object | None = None,
) -> InspectionPipeline:
    config = load_pipeline_config(EXAMPLE_PIPELINE)
    rule = load_rule_definition(EXAMPLE_RULE)
    product_manifest = load_model_manifest(PRODUCT_MANIFEST)
    component_manifest = load_model_manifest(COMPONENT_MANIFEST)
    return InspectionPipeline(
        product_detector=product_detector,  # type: ignore[arg-type]
        component_detector=component_detector,  # type: ignore[arg-type]
        roi_engine=ROIEngine(config.roi),
        rule_engine=rule_engine or RuleEngine(),  # type: ignore[arg-type]
        rule=rule,
        product_manifest=product_manifest,
        component_manifest=component_manifest,
        config=config,
        device_id=uuid4(),
    )


def _product_detection(frame_id: UUID, width: int = 800, height: int = 600) -> ProductDetection:
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
        quality=FrameQuality(
            usable=True, blur_score=0.0, brightness_mean=0.0, saturation_fraction=0.0
        ),
    )


def _component_obs(
    frame_id: UUID,
    code: str,
    roi_size: tuple[int, int] = (680, 512),
    frame_size: tuple[int, int] = (800, 600),
) -> ComponentDetection:
    roi_width, roi_height = roi_size
    frame_width, frame_height = frame_size
    return ComponentDetection(
        frame_id=frame_id,
        component_code=code,
        confidence=0.9,
        roi_bbox=BoundingBox(
            x_min=10.0,
            y_min=10.0,
            x_max=100.0,
            y_max=100.0,
            image_width=roi_width,
            image_height=roi_height,
        ),
        full_frame_bbox=BoundingBox(
            x_min=70.0,
            y_min=54.0,
            x_max=160.0,
            y_max=144.0,
            image_width=frame_width,
            image_height=frame_height,
        ),
        model_version_id=load_model_manifest(COMPONENT_MANIFEST).model_version_id,
    )


def _write_image(path: Path) -> None:
    Image.new("RGB", (800, 600), (180, 180, 180)).save(path)


def test_ok_when_all_components_present(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector(
        [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
    )
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))), component_detector
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.OK
    assert record.decision.reason_codes == []
    assert all(evidence.state == "PRESENT" for evidence in record.evidence)
    inspection_dir = tmp_path / "out" / str(record.inspection_id)
    assert (inspection_dir / "product_roi.jpg").is_file()
    assert (inspection_dir / "annotated_frame.jpg").is_file()


def test_barcode_required_identity_is_verified_and_persisted(tmp_path: Path) -> None:
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        FakeComponentDetector(
            [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
        ),
    )
    pipeline._rule.barcode_required = True  # noqa: SLF001
    identity = resolve_barcode_identity(
        (BarcodeObservation("ABC", "QRCode", BarcodeSource.ZXING_CPP, datetime.now(UTC)),),
        BarcodeIdentityConfig(
            True, True, ("QRCode",), tmp_path / "barcodes.yaml", {"ABC": "model_a"}
        ),
        pipeline._rule.product_type,  # noqa: SLF001
    )

    record = pipeline.inspect_frame(
        CapturedFrame(0, datetime.now(UTC), 1, "RGB", "OK", Image.new("RGB", (800, 600))),
        OutputWriter(tmp_path / "out"),
        identity=identity,
    )

    assert record.decision.business_result is BusinessResult.OK
    assert record.barcode_result.value == "ABC"
    assert record.product_resolution.source == "BARCODE"


def test_barcode_required_unverified_identity_cannot_be_ok(tmp_path: Path) -> None:
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        FakeComponentDetector(
            [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
        ),
    )
    pipeline._rule.barcode_required = True  # noqa: SLF001
    identity = resolve_barcode_identity(
        (),
        BarcodeIdentityConfig(True, True, (), tmp_path / "barcodes.yaml", {"ABC": "model_a"}),
        pipeline._rule.product_type,  # noqa: SLF001
    )

    record = pipeline.inspect_frame(
        CapturedFrame(0, datetime.now(UTC), 1, "RGB", "OK", Image.new("RGB", (800, 600))),
        identity=identity,
    )

    assert record.decision.business_result is BusinessResult.NG
    assert rc.PRODUCT_IDENTITY_UNVERIFIED in record.decision.reason_codes


def test_enabled_barcode_identity_unverified_cannot_be_ok_when_rule_is_optional(
    tmp_path: Path,
) -> None:
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        FakeComponentDetector(
            [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
        ),
    )
    barcode_identity = BarcodeIdentityConfig(
        True, False, (), tmp_path / "barcodes.yaml", {"ABC": "model_a"}
    )
    pipeline._config = replace(  # noqa: SLF001
        pipeline._config,  # noqa: SLF001
        barcode_identity=barcode_identity,
    )
    identity = resolve_barcode_identity(
        (),
        barcode_identity,
        pipeline._rule.product_type,  # noqa: SLF001
    )

    record = pipeline.inspect_frame(
        CapturedFrame(0, datetime.now(UTC), 1, "RGB", "OK", Image.new("RGB", (800, 600))),
        identity=identity,
    )

    assert record.decision.business_result is BusinessResult.NG
    assert rc.BARCODE_UNREADABLE in record.decision.reason_codes


def test_rule_evaluation_error_is_persisted_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector(
        [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
    )
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        component_detector,
        rule_engine=RaisingRuleEngine(),
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.NG
    assert record.decision.internal_decision.value == "NG"
    assert "RULE_EVALUATION_ERROR" in record.decision.reason_codes
    assert len(record.evidence) == 3
    # Provenance remains present in the persisted record.
    assert record.product_model_version_id is not None
    assert record.component_model_version_id is not None
    assert record.rule_version_id is not None
    inspection_dir = tmp_path / "out" / str(record.inspection_id)
    assert (inspection_dir / "inspection.json").is_file()


def test_product_detector_failure_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector([])
    pipeline = _build_pipeline(RaisingProductDetector(), component_detector)
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes
    assert all(evidence.state == "UNCERTAIN" for evidence in record.evidence)
    inspection_dir = tmp_path / "out" / str(record.inspection_id)
    assert not (inspection_dir / "product_roi.jpg").exists()


def test_no_product_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(reason_code="NO_PRODUCT")), FakeComponentDetector([])
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.NG
    assert "NO_PRODUCT" in record.decision.reason_codes


def test_missing_component_produces_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector(
        [_component_obs(uuid4(), c) for c in ("component_b", "manual")]
    )
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))), component_detector
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.NG
    assert "COMPONENT_MISSING:component_a" in record.decision.reason_codes
    assert "component_a" in record.decision.missing_components


def test_image_read_error_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "broken.png"
    image_path.write_bytes(b"not a real image")
    pipeline = _build_pipeline(FakeProductDetector(_Outcome()), FakeComponentDetector([]))
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.NG
    assert "IMAGE_READ_ERROR" in record.decision.reason_codes


def test_component_inference_failure_is_uncertain_not_missing(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        RaisingComponentDetector(),
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes
    assert all(evidence.state == "UNCERTAIN" for evidence in record.evidence)
    assert all(
        rc.COMPONENT_UNVERIFIABLE in evidence.policy_reason_codes for evidence in record.evidence
    )


def test_json_output_contains_versions(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector(
        [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
    )
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))), component_detector
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    payload = json.loads(
        (tmp_path / "out" / str(record.inspection_id) / "inspection.json").read_text()
    )
    assert payload["decision"]["business_result"] == "OK"
    assert payload["product_model_version_id"]
    assert payload["component_model_version_id"]
    assert payload["rule_version_id"]
    assert payload["aggregation_policy_version"] == "single-frame-mvp-1"
    assert payload["synchronization_status"] == "LOCAL_ONLY"
    persisted = InspectionRecord.model_validate_json(
        (tmp_path / "out" / str(record.inspection_id) / "inspection.json").read_text()
    )
    assert persisted.inspection_id == record.inspection_id


def test_stale_product_frame_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    pipeline = _build_pipeline(
        StaleFrameProductDetector(),
        FakeComponentDetector([]),
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes
    assert all(evidence.state == "UNCERTAIN" for evidence in record.evidence)


class SettingsAwareProductDetector(FakeProductDetector):
    @property
    def effective_settings(self) -> dict[str, object]:
        return {"imgsz": [640, 640], "conf": 0.5, "iou": 0.5, "device": None}


class SettingsAwareComponentDetector(FakeComponentDetector):
    @property
    def effective_settings(self) -> dict[str, object]:
        return {"imgsz": [512, 680], "conf": 0.0, "iou": 0.5, "device": None}


def test_inference_metadata_records_both_stages(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    pipeline = _build_pipeline(
        SettingsAwareProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        SettingsAwareComponentDetector(
            [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
        ),
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.inference_metadata is not None
    product = record.inference_metadata.product_detection
    component = record.inference_metadata.component_detection
    assert product is not None and component is not None
    assert product.settings.imgsz == [640, 640]
    assert component.settings.imgsz == [512, 680]
    assert component.model_version != ""
    assert component.latency_ms >= 0


def test_inference_metadata_is_persisted(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector(
        [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
    )
    pipeline = _build_pipeline(
        SettingsAwareProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        component_detector,
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.inference_metadata is not None
    product_meta = record.inference_metadata.product_detection
    assert product_meta is not None
    assert product_meta.settings.conf == pytest.approx(0.5)
    assert product_meta.model_version != ""
    assert product_meta.latency_ms >= 0
    payload = json.loads(
        (tmp_path / "out" / str(record.inspection_id) / "inspection.json").read_text()
    )
    persisted = payload["inference_metadata"]["product_detection"]
    assert persisted["settings"]["imgsz"] == [640, 640]
    assert persisted["model_name"]
    assert persisted["timestamp"]


class WrongModelProductDetector:
    """Returns a product detection carrying the wrong model version ID."""

    def detect(self, frame: Image.Image, frame_id: UUID) -> object:
        detection = _product_detection(frame_id, frame.width, frame.height)
        detection.model_version_id = uuid4()
        return _Outcome(selected=detection)


def test_product_provenance_model_mismatch_is_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    pipeline = _build_pipeline(WrongModelProductDetector(), FakeComponentDetector([]))
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes
    assert all(evidence.state == "UNCERTAIN" for evidence in record.evidence)


def _build_component_obs(frame_id: UUID, code: str) -> ComponentDetection:
    return _component_obs(frame_id, code, (680, 512), (800, 600))


def _wrong_component_detector(code: str = "component_a") -> FakeComponentDetector:
    obs = _build_component_obs(uuid4(), code)
    return FakeComponentDetector([obs])


class DimsMismatchComponentDetector:
    """Returns observations whose full-frame dims do not match the frame."""

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: tuple[str, ...],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        obs = _component_obs(
            frame_id, "component_a", (roi.width, roi.height), (frame_size[0], frame_size[1])
        )
        obs.full_frame_bbox.image_width = frame_size[0] + 1
        return [obs]


class StaleFrameComponentDetector:
    """Returns observations bound to a different frame ID than requested."""

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: tuple[str, ...],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        return [_component_obs(uuid4(), "component_a", (roi.width, roi.height), frame_size)]


class WrongModelComponentDetector:
    """Returns observations carrying the wrong component model version."""

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: tuple[str, ...],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        obs = _component_obs(frame_id, "component_a", (roi.width, roi.height), frame_size)
        obs.model_version_id = uuid4()
        return [obs]


class InconsistentCoordinateComponentDetector:
    """Returns a full-frame box that does not match the recorded transform."""

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: tuple[str, ...],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        obs = _component_obs(frame_id, "component_a", (roi.width, roi.height), frame_size)
        obs.full_frame_bbox = BoundingBox(
            x_min=obs.full_frame_bbox.x_min + 50.0,
            y_min=obs.full_frame_bbox.y_min,
            x_max=obs.full_frame_bbox.x_max + 50.0,
            y_max=obs.full_frame_bbox.y_max,
            image_width=obs.full_frame_bbox.image_width,
            image_height=obs.full_frame_bbox.image_height,
        )
        return [obs]


class ScaledTransformComponentDetector:
    """Returns observations under a non-translation (scaled) transform."""

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: tuple[str, ...],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        obs = _component_obs(frame_id, "component_a", (roi.width, roi.height), frame_size)
        # A valid scaled mapping that the M1 pipeline must reject as unsupported.
        obs.full_frame_bbox = BoundingBox(
            x_min=obs.roi_bbox.x_min * 2.0,
            y_min=obs.roi_bbox.y_min * 2.0,
            x_max=obs.roi_bbox.x_max * 2.0,
            y_max=obs.roi_bbox.y_max * 2.0,
            image_width=obs.full_frame_bbox.image_width,
            image_height=obs.full_frame_bbox.image_height,
        )
        return [obs]


def _run_with_component_detector(tmp_path: Path, detector: object) -> InspectionRecord:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))), detector
    )
    return pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )


def test_is_translation_transform_rejects_non_translation() -> None:
    from assemblyvision_edge.pipeline import _is_translation_transform

    assert _is_translation_transform((1.0, 0.0, -60.0, 0.0, 1.0, -44.0))
    assert not _is_translation_transform((2.0, 0.0, -60.0, 0.0, 1.0, -44.0))


def test_provenance_rejects_non_translation_transform() -> None:
    from assemblyvision_edge.pipeline import _validate_component_provenance

    manifest = load_model_manifest(COMPONENT_MANIFEST)
    obs = _component_obs(uuid4(), "component_a")
    assert (
        _validate_component_provenance(
            [obs],
            obs.frame_id,
            manifest,
            Image.new("RGB", (680, 512)),
            Image.new("RGB", (800, 600)),
            (2.0, 0.0, -60.0, 0.0, 1.0, -44.0),
        )
        is False
    )


def test_provenance_uses_absolute_tolerance_only_at_large_coordinates() -> None:
    from assemblyvision_edge.pipeline import _validate_component_provenance

    # The tolerance must be purely absolute (F12): at coordinates near 1e9 the
    # old default rel_tol=1e-9 would accept a ~1px discrepancy, so a 0.5 offset
    # must fail closed instead of passing. model_construct skips the
    # in-image bound checks so the tolerance path itself is exercised.
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    frame_id = uuid4()
    roi = Image.new("RGB", (680, 512))
    frame = Image.new("RGB", (800, 600))
    base = 1_000_000_000.0
    obs = ComponentDetection.model_construct(
        frame_id=frame_id,
        component_code="component_a",
        confidence=0.9,
        roi_bbox=BoundingBox.model_construct(
            x_min=base,
            y_min=base,
            x_max=base + 90.0,
            y_max=base + 90.0,
            image_width=roi.width,
            image_height=roi.height,
        ),
        full_frame_bbox=BoundingBox.model_construct(
            x_min=base + 60.5,
            y_min=base + 44.5,
            x_max=base + 150.5,
            y_max=base + 134.5,
            image_width=frame.width,
            image_height=frame.height,
        ),
        model_version_id=manifest.model_version_id,
    )
    assert (
        _validate_component_provenance(
            [obs], frame_id, manifest, roi, frame, (1.0, 0.0, -60.0, 0.0, 1.0, -44.0)
        )
        is False
    )


def test_component_stale_frame_is_ng(tmp_path: Path) -> None:
    record = _run_with_component_detector(tmp_path, StaleFrameComponentDetector())
    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes


def test_component_wrong_model_is_ng(tmp_path: Path) -> None:
    record = _run_with_component_detector(tmp_path, WrongModelComponentDetector())
    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes


def test_component_dimension_mismatch_is_ng(tmp_path: Path) -> None:
    record = _run_with_component_detector(tmp_path, DimsMismatchComponentDetector())
    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes


def test_component_inconsistent_transform_is_ng(tmp_path: Path) -> None:
    record = _run_with_component_detector(tmp_path, InconsistentCoordinateComponentDetector())
    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes


def test_component_scaled_transform_is_rejected_for_m1(tmp_path: Path) -> None:
    record = _run_with_component_detector(tmp_path, ScaledTransformComponentDetector())
    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes


def test_component_roi_dims_mismatch_is_ng(tmp_path: Path) -> None:
    record = _run_with_component_detector(tmp_path, RoiDimsMismatchComponentDetector())
    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes


class RoiDimsMismatchComponentDetector:
    """Returns observations whose ROI dims do not match the generated ROI."""

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: tuple[str, ...],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        obs = _component_obs(frame_id, "component_a", (roi.width, roi.height), frame_size)
        obs.roi_bbox.image_width = roi.width + 1
        return [obs]


class RaisingROIEngine:
    def generate(self, frame: Image.Image, frame_id: UUID, product_box: object) -> object:
        raise ROIGenerationError(rc.ROI_INVALID)


def test_roi_failure_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    config = load_pipeline_config(EXAMPLE_PIPELINE)
    rule = load_rule_definition(EXAMPLE_RULE)
    pipeline = InspectionPipeline(
        product_detector=FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))),  # type: ignore[arg-type]
        component_detector=FakeComponentDetector([]),  # type: ignore[arg-type]
        roi_engine=RaisingROIEngine(),  # type: ignore[arg-type]
        rule_engine=RuleEngine(),
        rule=rule,
        product_manifest=load_model_manifest(PRODUCT_MANIFEST),
        component_manifest=load_model_manifest(COMPONENT_MANIFEST),
        config=config,
        device_id=uuid4(),
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )

    assert record.decision.business_result is BusinessResult.NG
    assert "ROI_INVALID" in record.decision.reason_codes


def test_artifact_checksum_empty_manifest() -> None:
    from assemblyvision_edge.pipeline import _artifact_checksum

    manifest = load_model_manifest(PRODUCT_MANIFEST)
    manifest.artifacts = []
    assert _artifact_checksum(manifest) == "0" * 64


def test_inference_metadata_projection_persists_through_repository(tmp_path: Path) -> None:
    """Regression: the SQLite projection must serialize inference metadata.

    The writer path serializes the full record (model_dump mode=json), but the
    repository projection previously re-serialized the raw Pydantic object,
    which is not JSON serializable and broke persisted dev uploads (PR-028).
    """
    from assemblyvision_edge.persistence.repository import EdgeRepository

    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector(
        [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
    )
    pipeline = _build_pipeline(
        SettingsAwareProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        component_detector,
    )
    record = pipeline.inspect_image(
        FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out")
    )
    assert record.inference_metadata is not None

    repo = EdgeRepository.open(str(tmp_path / "edge.sqlite3"))
    try:
        repo.persist_inspection_and_enqueue_uploads(record)
        stored = repo.get_inspection(str(record.inspection_id))
    finally:
        repo.close()

    assert stored is not None
    assert stored.inference_metadata is not None
    product_meta = stored.inference_metadata.product_detection
    assert product_meta is not None
    assert product_meta.model_version != ""
    assert product_meta.settings.conf == pytest.approx(0.5)
