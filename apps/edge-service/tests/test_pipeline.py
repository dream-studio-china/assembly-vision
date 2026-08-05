"""Tests for pipeline orchestration and fail-safe behavior."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from assemblyvision_domain.models import BusinessResult, InspectionRecord
from assemblyvision_edge.config import load_pipeline_config, load_rule_definition
from assemblyvision_edge.detection import ComponentDetector, ProductDetector
from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.pipeline import InspectionPipeline
from assemblyvision_edge.rules.rule_engine import RuleEngine
from assemblyvision_vision.manifests import load_model_manifest
from assemblyvision_vision.roi.roi_engine import ROIEngine
from assemblyvision_vision.sources.folder_source import FolderSource
from PIL import Image

from tests.conftest import COMPONENT_MANIFEST, EXAMPLE_PIPELINE, EXAMPLE_RULE, PRODUCT_MANIFEST


def _build_pipeline() -> InspectionPipeline:
    config = load_pipeline_config(EXAMPLE_PIPELINE)
    rule = load_rule_definition(EXAMPLE_RULE)
    product_manifest = load_model_manifest(PRODUCT_MANIFEST)
    component_manifest = load_model_manifest(COMPONENT_MANIFEST)
    return InspectionPipeline(
        product_detector=ProductDetector.from_manifest(product_manifest, config.product_detection),
        component_detector=ComponentDetector.from_manifest(
            component_manifest, config.component_detection, config.components
        ),
        roi_engine=ROIEngine(config.roi),
        rule_engine=RuleEngine(),
        rule=rule,
        product_manifest=product_manifest,
        component_manifest=component_manifest,
        config=config,
        device_id=uuid4(),
    )


def test_detector_failure_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    Image.new("RGB", (400, 300), (180, 180, 180)).save(image_path)
    output_root = tmp_path / "out"
    pipeline = _build_pipeline()
    source = FolderSource(tmp_path)
    record = pipeline.inspect_image(source, image_path, OutputWriter(output_root))

    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes
    assert all(evidence.state == "UNCERTAIN" for evidence in record.evidence)
    inspection_dir = output_root / str(record.inspection_id)
    assert (inspection_dir / "inspection.json").is_file()
    assert (inspection_dir / "key_frame.jpg").is_file()
    assert (inspection_dir / "annotated_frame.jpg").is_file()
    assert not (inspection_dir / "product_roi.jpg").exists()
    persisted = InspectionRecord.model_validate_json((inspection_dir / "inspection.json").read_text())
    assert persisted.inspection_id == record.inspection_id


def test_image_read_error_is_failsafe_ng(tmp_path: Path) -> None:
    image_path = tmp_path / "broken.png"
    image_path.write_bytes(b"not a real image")
    output_root = tmp_path / "out"
    pipeline = _build_pipeline()
    source = FolderSource(tmp_path)
    record = pipeline.inspect_image(source, image_path, OutputWriter(output_root))

    assert record.decision.business_result is BusinessResult.NG
    assert "IMAGE_READ_ERROR" in record.decision.reason_codes
    assert any(reason.reason_code == "IMAGE_READ_ERROR" for reason in record.frame_quality_summary.reasons)


def test_json_output_is_valid_and_contains_versions(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    Image.new("RGB", (400, 300), (180, 180, 180)).save(image_path)
    output_root = tmp_path / "out"
    pipeline = _build_pipeline()
    source = FolderSource(tmp_path)
    record = pipeline.inspect_image(source, image_path, OutputWriter(output_root))
    payload = json.loads((output_root / str(record.inspection_id) / "inspection.json").read_text())
    assert payload["decision"]["business_result"] == "NG"
    assert payload["product_model_version_id"]
    assert payload["component_model_version_id"]
    assert payload["rule_version_id"]
    assert payload["aggregation_policy_version"] == "single-frame-mvp-1"
    assert payload["synchronization_status"] == "LOCAL_ONLY"
