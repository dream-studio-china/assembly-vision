"""Tests for the real product and component detector adapters."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from assemblyvision_domain.errors import ConfigError, DetectionError
from assemblyvision_domain.models import ModelManifest
from assemblyvision_edge.config import ComponentDetectionSettings, DetectionSettings
from assemblyvision_edge.detection.component_detector import ComponentDetector
from assemblyvision_edge.detection.product_detector import ProductDetector
from assemblyvision_vision.manifests import load_model_manifest
from PIL import Image

from tests.conftest import COMPONENT_MANIFEST, PRODUCT_MANIFEST


class _Boxes:
    def __init__(self, raw: list[tuple[float, float, tuple[float, float, float, float]]]) -> None:
        self.cls = [r[0] for r in raw]
        self.conf = [r[1] for r in raw]
        self.xyxy = [r[2] for r in raw]

    def __len__(self) -> int:
        return len(self.cls)


class _Results:
    def __init__(self, raw: list[tuple[float, float, tuple[float, float, float, float]]]) -> None:
        self.boxes = _Boxes(raw) if raw else None


class FakeModel:
    def __init__(self, raw: list[tuple[float, float, tuple[float, float, float, float]]]) -> None:
        self._raw = raw
        self.calls: list[dict[str, object]] = []

    def __call__(self, frame: Image.Image, **kwargs: object) -> list[_Results]:
        self.calls.append(kwargs)
        return [_Results(self._raw)]


def _product_settings() -> DetectionSettings:
    return DetectionSettings(
        model_version="product-yolo-1.0.0", confidence_threshold=0.5, iou_threshold=0.5
    )


def _component_settings() -> DetectionSettings:
    return DetectionSettings(
        model_version="component-yolo-1.0.0", confidence_threshold=0.0, iou_threshold=0.5
    )


def _components() -> dict[str, ComponentDetectionSettings]:
    return {
        "component_a": ComponentDetectionSettings(observation_threshold=0.5),
        "component_b": ComponentDetectionSettings(observation_threshold=0.5),
        "manual": ComponentDetectionSettings(observation_threshold=0.5),
    }


def _non_square_manifest(
    task: Literal["PRODUCT_DETECTION", "COMPONENT_DETECTION"],
) -> ModelManifest:
    return ModelManifest(
        model_version_id=uuid4(),
        model_id=uuid4(),
        semantic_version="1.0.0",
        task=task,
        runtime="ultralytics",
        input_width=1280,
        input_height=736,
        class_names=(
            ["product"] if task == "PRODUCT_DETECTION" else ["component_a", "component_b", "manual"]
        ),
        split_strategy="held-out",
        source_revision="r1",
        training_config_revision="t1",
        created_at=datetime.now(UTC),
    )


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
    model = FakeModel(
        [(0, 0.9, (10.0, 10.0, 200.0, 200.0)), (0, 0.8, (400.0, 300.0, 700.0, 500.0))]
    )
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


@pytest.mark.parametrize(
    "raw",
    [
        [(-1.0, 0.9, (100.0, 80.0, 700.0, 520.0))],
        [(0.5, 0.9, (100.0, 80.0, 700.0, 520.0))],
        [(0.0, math.nan, (100.0, 80.0, 700.0, 520.0))],
        [(0.0, 0.9, (100.0, 80.0, math.nan, 520.0))],
        [(0.0, 0.9, (100.0, 80.0, 900.0, 520.0))],
    ],
)
def test_product_detector_rejects_malformed_output(
    raw: list[tuple[float, float, tuple[float, float, float, float]]],
) -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    detector = ProductDetector(manifest, _product_settings(), FakeModel(raw))

    with pytest.raises(DetectionError) as exc_info:
        detector.detect(Image.new("RGB", (800, 600), (0, 0, 0)), uuid4())

    assert exc_info.value.reason_code == "INFERENCE_ERROR"


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
            (0, 0.9, (10.0, 10.0, 100.0, 100.0)),  # component_a, required, above 0.5
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


@pytest.mark.parametrize(
    "raw",
    [
        [(-1.0, 0.9, (10.0, 10.0, 100.0, 100.0))],
        [(0.5, 0.9, (10.0, 10.0, 100.0, 100.0))],
        [(0.0, math.nan, (10.0, 10.0, 100.0, 100.0))],
        [(0.0, 0.9, (10.0, 10.0, 700.0, 100.0))],
    ],
)
def test_component_detector_rejects_malformed_output(
    raw: list[tuple[float, float, tuple[float, float, float, float]]],
) -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    detector = ComponentDetector(manifest, _component_settings(), _components(), FakeModel(raw))

    with pytest.raises(DetectionError) as exc_info:
        detector.detect(
            Image.new("RGB", (680, 512), (0, 0, 0)),
            uuid4(),
            ("component_a",),
            (1.0, 0.0, -60.0, 0.0, 1.0, -44.0),
            (800, 600),
        )

    assert exc_info.value.reason_code == "INFERENCE_ERROR"


def test_from_manifest_rejects_missing_weights(tmp_path: object) -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    with pytest.raises(ConfigError):
        ProductDetector.from_manifest(manifest, _product_settings(), tmp_path)


def test_product_detector_passes_manifest_inference_settings() -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    model = FakeModel([(0, 0.9, (100.0, 80.0, 700.0, 520.0))])
    detector = ProductDetector(manifest, _product_settings(), model)
    detector.detect(Image.new("RGB", (800, 600), (128, 128, 128)), uuid4())

    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["imgsz"] == (manifest.input_height, manifest.input_width)
    assert call["conf"] == pytest.approx(0.5)
    assert call["iou"] == pytest.approx(0.5)
    assert "device" in call
    assert detector.effective_settings["imgsz"] == [manifest.input_height, manifest.input_width]


def test_component_detector_passes_manifest_inference_settings() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    model = FakeModel([(0, 0.9, (10.0, 10.0, 100.0, 100.0))])
    detector = ComponentDetector(manifest, _component_settings(), _components(), model)
    detector.detect(
        Image.new("RGB", (680, 512), (128, 128, 128)),
        uuid4(),
        ("component_a",),
        (1.0, 0.0, -60.0, 0.0, 1.0, -44.0),
        (800, 600),
    )

    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["imgsz"] == (manifest.input_height, manifest.input_width)
    assert call["conf"] == pytest.approx(0.0)
    assert call["iou"] == pytest.approx(0.5)
    assert detector.effective_settings["imgsz"] == [manifest.input_height, manifest.input_width]


def test_product_detector_imgsz_is_height_width_for_non_square_manifest() -> None:
    manifest = _non_square_manifest("PRODUCT_DETECTION")
    model = FakeModel([(0, 0.9, (100.0, 80.0, 700.0, 520.0))])
    detector = ProductDetector(manifest, _product_settings(), model)
    detector.detect(Image.new("RGB", (800, 600), (128, 128, 128)), uuid4())

    assert model.calls[0]["imgsz"] == (736, 1280)
    assert detector.effective_settings["imgsz"] == [736, 1280]


def test_component_detector_imgsz_is_height_width_for_non_square_manifest() -> None:
    manifest = _non_square_manifest("COMPONENT_DETECTION")
    model = FakeModel([(0, 0.9, (10.0, 10.0, 100.0, 100.0))])
    detector = ComponentDetector(manifest, _component_settings(), _components(), model)
    detector.detect(
        Image.new("RGB", (680, 512), (0, 0, 0)),
        uuid4(),
        ("component_a",),
        (1.0, 0.0, -60.0, 0.0, 1.0, -44.0),
        (800, 600),
    )

    assert model.calls[0]["imgsz"] == (736, 1280)
    assert detector.effective_settings["imgsz"] == [736, 1280]


def test_component_detector_rejects_wrong_task() -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    with pytest.raises(ConfigError, match="not COMPONENT_DETECTION"):
        ComponentDetector(manifest, _component_settings(), _components(), FakeModel([]))


def test_component_detector_rejects_missing_configured_classes() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    components = {"unknown_component": ComponentDetectionSettings(observation_threshold=0.5)}
    with pytest.raises(ConfigError, match="class_names missing configured components"):
        ComponentDetector(manifest, _component_settings(), components, FakeModel([]))


def test_component_detector_filters_out_of_range_class_ids() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    model = FakeModel([(99, 0.9, (10.0, 10.0, 100.0, 100.0))])
    detector = ComponentDetector(manifest, _component_settings(), _components(), model)
    observations = detector.detect(
        Image.new("RGB", (680, 512), (0, 0, 0)),
        uuid4(),
        ("component_a",),
        (1.0, 0.0, -60.0, 0.0, 1.0, -44.0),
        (800, 600),
    )
    assert observations == []


def test_component_detector_filters_unrequired_class() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    model = FakeModel([(1, 0.99, (10.0, 10.0, 100.0, 100.0))])  # component_b, not required
    detector = ComponentDetector(manifest, _component_settings(), _components(), model)
    observations = detector.detect(
        Image.new("RGB", (680, 512), (0, 0, 0)),
        uuid4(),
        ("component_a",),
        (1.0, 0.0, -60.0, 0.0, 1.0, -44.0),
        (800, 600),
    )
    assert observations == []


def test_component_detector_filters_below_threshold() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    model = FakeModel([(0, 0.1, (10.0, 10.0, 100.0, 100.0))])  # component_a, conf 0.1 < 0.5
    detector = ComponentDetector(manifest, _component_settings(), _components(), model)
    observations = detector.detect(
        Image.new("RGB", (680, 512), (0, 0, 0)),
        uuid4(),
        ("component_a",),
        (1.0, 0.0, -60.0, 0.0, 1.0, -44.0),
        (800, 600),
    )
    assert observations == []


def test_product_detector_rejects_wrong_task() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    with pytest.raises(ConfigError, match="not PRODUCT_DETECTION"):
        ProductDetector(manifest, _product_settings(), FakeModel([]))


def test_product_detector_rejects_missing_product_class() -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    manifest.class_names = ["not_product"]
    with pytest.raises(ConfigError, match="class_names missing configured product classes"):
        ProductDetector(manifest, _product_settings(), FakeModel([]))


class _NoResultsModel:
    def __call__(self, frame: Image.Image, **kwargs: object) -> list[object]:
        return []


def test_product_detector_empty_results_is_no_product() -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    detector = ProductDetector(manifest, _product_settings(), _NoResultsModel())
    outcome = detector.detect(Image.new("RGB", (800, 600), (0, 0, 0)), uuid4())
    assert outcome.selected is None
    assert outcome.reason_code == "NO_PRODUCT"


class _RaisingModel:
    def __call__(self, frame: Image.Image, **kwargs: object) -> object:
        raise ValueError("model exploded")


def test_product_detector_surfaces_inference_error() -> None:
    manifest = load_model_manifest(PRODUCT_MANIFEST)
    detector = ProductDetector(manifest, _product_settings(), _RaisingModel())
    with pytest.raises(DetectionError) as exc_info:
        detector.detect(Image.new("RGB", (800, 600), (0, 0, 0)), uuid4())
    assert exc_info.value.reason_code == "INFERENCE_ERROR"


class _EmptyResultsModel:
    def __call__(self, frame: Image.Image, **kwargs: object) -> list[object]:
        return []


def test_component_detector_empty_results() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    detector = ComponentDetector(
        manifest, _component_settings(), _components(), _EmptyResultsModel()
    )
    observations = detector.detect(
        Image.new("RGB", (680, 512), (0, 0, 0)),
        uuid4(),
        ("component_a",),
        (1.0, 0.0, -60.0, 0.0, 1.0, -44.0),
        (800, 600),
    )
    assert observations == []


class _FakeUltralyticsModel:
    names = {0: "product", 1: "component_a", 2: "component_b", 3: "manual"}


def test_from_manifest_loads_and_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    manifest = load_model_manifest(PRODUCT_MANIFEST)

    monkeypatch.setattr(
        "assemblyvision_edge.detection.product_detector.verify_manifest_artifact",
        lambda manifest, path: weights,
    )
    monkeypatch.setattr(
        "assemblyvision_edge.detection.product_detector.verify_model_class_map",
        lambda names, manifest: None,
    )
    monkeypatch.setattr("ultralytics.YOLO", lambda path: _FakeUltralyticsModel())
    detector = ProductDetector.from_manifest(manifest, _product_settings(), tmp_path / "m.json")
    assert isinstance(detector, ProductDetector)
    assert detector.effective_settings["imgsz"] == [manifest.input_height, manifest.input_width]


def test_component_from_manifest_loads_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    manifest = load_model_manifest(COMPONENT_MANIFEST)

    monkeypatch.setattr(
        "assemblyvision_edge.detection.component_detector.verify_manifest_artifact",
        lambda manifest, path: weights,
    )
    monkeypatch.setattr(
        "assemblyvision_edge.detection.component_detector.verify_model_class_map",
        lambda names, manifest: None,
    )
    monkeypatch.setattr("ultralytics.YOLO", lambda path: _FakeUltralyticsModel())
    detector = ComponentDetector.from_manifest(
        manifest, _component_settings(), _components(), tmp_path / "m.json"
    )
    assert isinstance(detector, ComponentDetector)
