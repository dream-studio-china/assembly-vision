"""Tests for pipeline orchestration and fail-safe behavior."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.errors import DetectionError
from assemblyvision_domain.models import (
    BoundingBox,
    BusinessResult,
    ComponentDetection,
    FrameQuality,
    InspectionRecord,
    ProductDetection,
)
from assemblyvision_edge.config import load_pipeline_config, load_rule_definition
from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.pipeline import InspectionPipeline
from assemblyvision_edge.rules.rule_engine import RuleEngine
from assemblyvision_vision.manifests import load_model_manifest
from assemblyvision_vision.roi.roi_engine import ROIEngine
from assemblyvision_vision.sources.folder_source import FolderSource
from PIL import Image

from tests.conftest import COMPONENT_MANIFEST, EXAMPLE_PIPELINE, EXAMPLE_RULE, PRODUCT_MANIFEST


class FakeProductDetector:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    def detect(self, frame: Image.Image, frame_id: UUID) -> object:
        return self._outcome


class RaisingProductDetector:
    def detect(self, frame: Image.Image, frame_id: UUID) -> object:
        raise DetectionError("INFERENCE_ERROR", "boom")


class FakeComponentDetector:
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
        return self._observations


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
    def __init__(self, selected: ProductDetection | None = None, reason_code: str | None = None) -> None:
        self.selected = selected
        self.reason_code = reason_code


def _build_pipeline(
    product_detector: object,
    component_detector: object,
) -> InspectionPipeline:
    config = load_pipeline_config(EXAMPLE_PIPELINE)
    rule = load_rule_definition(EXAMPLE_RULE)
    product_manifest = load_model_manifest(PRODUCT_MANIFEST)
    component_manifest = load_model_manifest(COMPONENT_MANIFEST)
    return InspectionPipeline(
        product_detector=product_detector,  # type: ignore[arg-type]
        component_detector=component_detector,  # type: ignore[arg-type]
        roi_engine=ROIEngine(config.roi),
        rule_engine=RuleEngine(),
        rule=rule,
        product_manifest=product_manifest,
        component_manifest=component_manifest,
        config=config,
        device_id=uuid4(),
    )


def _product_detection(frame_id: UUID) -> ProductDetection:
    return ProductDetection(
        frame_id=frame_id,
        product_class="product",
        confidence=0.95,
        bbox=BoundingBox(x_min=100.0, y_min=80.0, x_max=700.0, y_max=520.0, image_width=800, image_height=600),
        model_version_id=load_model_manifest(PRODUCT_MANIFEST).model_version_id,
        quality=FrameQuality(usable=True, blur_score=0.0, brightness_mean=0.0, saturation_fraction=0.0),
    )


def _component_obs(frame_id: UUID, code: str) -> ComponentDetection:
    return ComponentDetection(
        frame_id=frame_id,
        component_code=code,
        confidence=0.9,
        roi_bbox=BoundingBox(x_min=10.0, y_min=10.0, x_max=100.0, y_max=100.0, image_width=680, image_height=512),
        full_frame_bbox=BoundingBox(x_min=70.0, y_min=54.0, x_max=160.0, y_max=144.0, image_width=800, image_height=600),
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
    pipeline = _build_pipeline(FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))), component_detector)
    record = pipeline.inspect_image(FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out"))

    assert record.decision.business_result is BusinessResult.OK
    assert record.decision.reason_codes == []
    assert all(evidence.state == "PRESENT" for evidence in record.evidence)
    inspection_dir = tmp_path / "out" / str(record.inspection_id)
    assert (inspection_dir / "product_roi.jpg").is_file()
    assert (inspection_dir / "annotated_frame.jpg").is_file()


def test_product_detector_failure_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector([])
    pipeline = _build_pipeline(RaisingProductDetector(), component_detector)
    record = pipeline.inspect_image(FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out"))

    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes
    assert all(evidence.state == "UNCERTAIN" for evidence in record.evidence)
    inspection_dir = tmp_path / "out" / str(record.inspection_id)
    assert not (inspection_dir / "product_roi.jpg").exists()


def test_no_product_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    pipeline = _build_pipeline(FakeProductDetector(_Outcome(reason_code="NO_PRODUCT")), FakeComponentDetector([]))
    record = pipeline.inspect_image(FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out"))

    assert record.decision.business_result is BusinessResult.NG
    assert "NO_PRODUCT" in record.decision.reason_codes


def test_missing_component_produces_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector(
        [_component_obs(uuid4(), c) for c in ("component_b", "manual")]
    )
    pipeline = _build_pipeline(FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))), component_detector)
    record = pipeline.inspect_image(FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out"))

    assert record.decision.business_result is BusinessResult.NG
    assert "COMPONENT_MISSING:component_a" in record.decision.reason_codes
    assert "component_a" in record.decision.missing_components


def test_image_read_error_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "broken.png"
    image_path.write_bytes(b"not a real image")
    pipeline = _build_pipeline(FakeProductDetector(_Outcome()), FakeComponentDetector([]))
    record = pipeline.inspect_image(FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out"))

    assert record.decision.business_result is BusinessResult.NG
    assert "IMAGE_READ_ERROR" in record.decision.reason_codes


def test_component_inference_failure_is_uncertain_not_missing(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        RaisingComponentDetector(),
    )
    record = pipeline.inspect_image(FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out"))

    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes
    assert all(evidence.state == "UNCERTAIN" for evidence in record.evidence)
    assert all(rc.COMPONENT_UNVERIFIABLE in evidence.policy_reason_codes for evidence in record.evidence)


def test_json_output_contains_versions(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    component_detector = FakeComponentDetector(
        [_component_obs(uuid4(), c) for c in ("component_a", "component_b", "manual")]
    )
    pipeline = _build_pipeline(FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))), component_detector)
    record = pipeline.inspect_image(FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out"))

    payload = json.loads((tmp_path / "out" / str(record.inspection_id) / "inspection.json").read_text())
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
