"""Tests for the real product and component detector adapters."""

from __future__ import annotations

from uuid import uuid4

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_edge.config import ComponentDetectionSettings, DetectionSettings
from assemblyvision_edge.detection.component_detector import ComponentDetector
from assemblyvision_edge.detection.product_detector import ProductDetector
from assemblyvision_vision.manifests import load_model_manifest
from PIL import Image

from tests.conftest import COMPONENT_MANIFEST, PRODUCT_MANIFEST


class _Boxes:
    def __init__(self, raw: list[tuple[int, float, tuple[float, float, float, float]]]) -> None:
        self.cls = [r[0] for r in raw]
        self.conf = [r[1] for r in raw]
        self.xyxy = [r[2] for r in raw]

    def __len__(self) -> int:
        return len(self.cls)


class _Results:
    def __init__(self, raw: list[tuple[int, float, tuple[float, float, float, float]]]) -> None:
        self.boxes = _Boxes(raw) if raw else None


class FakeModel:
    def __init__(self, raw: list[tuple[int, float, tuple[float, float, float, float]]]) -> None:
        self._raw = raw

    def __call__(self, frame: Image.Image, verbose: bool = False) -> list[_Results]:
        return [_Results(self._raw)]


def _product_settings() -> DetectionSettings:
    return DetectionSettings(model_version="product-yolo-1.0.0", confidence_threshold=0.5, iou_threshold=0.5)


def _component_settings() -> DetectionSettings:
    return DetectionSettings(model_version="component-yolo-1.0.0", confidence_threshold=0.0, iou_threshold=0.5)


def _components() -> dict[str, ComponentDetectionSettings]:
    return {
        "component_a": ComponentDetectionSettings(observation_threshold=0.5),
        "component_b": ComponentDetectionSettings(observation_threshold=0.5),
        "manual": ComponentDetectionSettings(observation_threshold=0.5),
    }


def test_product_detector_selects_single_product() -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    model = FakeModel([(0, 0.9, (100.0, 80.0, 700.0, 520.0))])
    detector = ProductDetector(manifest, _product_settings(), model)
    frame = Image.new("RGB", (800, 600), (128, 128, 128))
    outcome = detector.detect(frame, uuid4())
    assert outcome.selected is not None
    assert outcome.selected.product_class == "product"
    assert outcome.selected.bbox.x_min == pytest.approx(100.0)
    assert outcome.reason_code is None


def test_product_detector_no_product() -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    detector = ProductDetector(manifest, _product_settings(), FakeModel([]))
    outcome = detector.detect(Image.new("RGB", (800, 600), (0, 0, 0)), uuid4())
    assert outcome.selected is None
    assert outcome.reason_code == "NO_PRODUCT"


def test_product_detector_multiple_products() -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    model = FakeModel([(0, 0.9, (10.0, 10.0, 200.0, 200.0)), (0, 0.8, (400.0, 300.0, 700.0, 500.0))])
    detector = ProductDetector(manifest, _product_settings(), model)
    outcome = detector.detect(Image.new("RGB", (800, 600), (0, 0, 0)), uuid4())
    assert outcome.selected is None
    assert outcome.reason_code == "MULTIPLE_PRODUCTS"


def test_product_detector_filters_below_confidence() -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    model = FakeModel([(0, 0.3, (100.0, 80.0, 700.0, 520.0))])
    detector = ProductDetector(manifest, _product_settings(), model)
    outcome = detector.detect(Image.new("RGB", (800, 600), (0, 0, 0)), uuid4())
    assert outcome.selected is None
    assert outcome.reason_code == "NO_PRODUCT"


def test_component_detector_maps_roi_to_full_frame() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    model = FakeModel([(0, 0.9, (10.0, 10.0, 100.0, 100.0))])  # component_a in ROI coords
    detector = ComponentDetector(manifest, _component_settings(), _components(), model)
    roi = Image.new("RGB", (680, 512), (128, 128, 128))
    transform = (1.0, 0.0, -60.0, 0.0, 1.0, -44.0)  # full->roi translation
    observations = detector.detect(roi, uuid4(), ("component_a",), transform, (800, 600))
    assert len(observations) == 1
    obs = observations[0]
    assert obs.component_code == "component_a"
    assert obs.roi_bbox.x_min == pytest.approx(10.0)
    assert obs.full_frame_bbox.x_min == pytest.approx(70.0)  # 10 + 60
    assert obs.full_frame_bbox.y_min == pytest.approx(54.0)  # 10 + 44


def test_component_detector_filters_unrequired_and_low_confidence() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    model = FakeModel(
        [
            (0, 0.9, (10.0, 10.0, 100.0, 100.0)),   # component_a, required, above 0.5
            (1, 0.4, (200.0, 200.0, 300.0, 300.0)),  # component_b, below threshold
            (2, 0.95, (400.0, 300.0, 500.0, 400.0)),  # manual, required
        ]
    )
    detector = ComponentDetector(manifest, _component_settings(), _components(), model)
    roi = Image.new("RGB", (680, 512), (128, 128, 128))
    observations = detector.detect(
        roi, uuid4(), ("component_a", "manual"), (1.0, 0.0, -60.0, 0.0, 1.0, -44.0), (800, 600)
    )
    codes = [obs.component_code for obs in observations]
    assert codes == ["component_a", "manual"]


def test_from_manifest_rejects_missing_weights(tmp_path: object) -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    with pytest.raises(ConfigError):
        ProductDetector.from_manifest(manifest, _product_settings(), tmp_path)  # type: ignore[arg-type]
