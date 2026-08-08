"""Tests for component dataset preparation (pure remap logic)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from assemblyvision_training.prepare_components import _remap_labels, prepare_component_dataset
from assemblyvision_vision.roi.roi_engine import ROIConfig
from PIL import Image


def test_remap_identity_transform(tmp_path: Path) -> None:
    lbl = tmp_path / "labels.txt"
    lbl.write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    transform = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    result = _remap_labels(lbl, 800, 600, 800, 600, transform)
    assert len(result) == 1
    parts = result[0].split()
    assert float(parts[1]) == pytest.approx(0.5)
    assert float(parts[2]) == pytest.approx(0.5)


def test_remap_full_frame_normalized_to_roi(tmp_path: Path) -> None:
    """Full-frame normalized labels must de-normalize with frame dims, not ROI dims."""
    lbl = tmp_path / "labels.txt"
    # component centered at (300, 300) in an 800x600 frame, 80x80 px
    # normalized: cx=0.375, cy=0.5, w=0.1, h=0.1333
    lbl.write_text("0 0.375 0.5 0.1 0.133333\n", encoding="utf-8")
    # ROI starts at offset (100, 50); ROI is 400x300
    transform = (1.0, 0.0, -100.0, 0.0, 1.0, -50.0)
    result = _remap_labels(lbl, 800, 600, 400, 300, transform)
    assert len(result) == 1
    parts = result[0].split()
    # ROI coords: center (300-100, 300-50) = (200, 250); size 80x80
    # normalized in 400x300 ROI: cx=200/400=0.5, cy=250/300=0.8333, w=80/400=0.2, h=80/300=0.2667
    assert float(parts[1]) == pytest.approx(0.5, abs=1e-3)
    assert float(parts[2]) == pytest.approx(0.8333, abs=1e-3)
    assert float(parts[3]) == pytest.approx(0.2, abs=1e-3)
    assert float(parts[4]) == pytest.approx(0.2667, abs=1e-3)


def test_remap_drops_boxes_outside_roi(tmp_path: Path) -> None:
    lbl = tmp_path / "labels.txt"
    lbl.write_text("0 0.05 0.05 0.1 0.1\n", encoding="utf-8")
    transform = (1.0, 0.0, -400.0, 0.0, 1.0, -300.0)
    result = _remap_labels(lbl, 800, 600, 400, 300, transform)
    assert len(result) == 0


def test_remap_empty_label_file(tmp_path: Path) -> None:
    lbl = tmp_path / "labels.txt"
    lbl.write_text("", encoding="utf-8")
    result = _remap_labels(lbl, 800, 600, 400, 300, (1.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    assert len(result) == 0


class _Tensor:
    def __init__(self, vals: list[float]) -> None:
        self._vals = vals

    def tolist(self) -> list[float]:
        return list(self._vals)

    def item(self) -> float:
        return self._vals[0]


class _Boxes:
    def __init__(self, boxes: list[list[float]], cls: list[int], conf: list[float]) -> None:
        self.xyxy = [_Tensor(b) for b in boxes]
        self.cls = [_Tensor([float(c)]) for c in cls]
        self.conf = [_Tensor([c]) for c in conf]

    def __len__(self) -> int:
        return len(self.xyxy)


class _Result:
    def __init__(
        self,
        boxes: list[list[float]],
        cls: list[int] | None = None,
        conf: list[float] | None = None,
    ) -> None:
        self.boxes = _Boxes(boxes, cls or [0] * len(boxes), conf or [0.9] * len(boxes))


class _FakeModel:
    names = {0: "product"}

    def __init__(self, result: _Result | None = None) -> None:
        self._result = result or _Result([[40.0, 30.0, 160.0, 120.0]])

    def __call__(
        self,
        frame: Image.Image,
        *,
        imgsz: tuple[int, int] | None = None,
        conf: float = 0.5,
        iou: float = 0.5,
        device: str | None = None,
        verbose: bool = False,
    ) -> list[_Result]:
        return [self._result]


def _make_product_manifest(tmp_path: Path, weights_bytes: bytes) -> Path:
    from assemblyvision_training.artifact import write_manifest

    weights = tmp_path / "product.pt"
    weights.write_bytes(weights_bytes)
    manifest_path = tmp_path / "product-manifest.json"
    write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    return manifest_path


def _make_source_dataset(tmp_path: Path) -> Path:
    d = tmp_path / "source"
    (d / "images" / "train").mkdir(parents=True)
    (d / "labels" / "train").mkdir(parents=True)
    Image.new("RGB", (200, 150), (128, 128, 128)).save(d / "images" / "train" / "img000.png")
    (d / "labels" / "train" / "img000.txt").write_text("", encoding="utf-8")
    (d / "data.yaml").write_text(
        yaml.dump(
            {
                "nc": 1,
                "names": ["chip"],
                "train": str((d / "images" / "train").resolve()),
                "val": str((d / "images" / "train").resolve()),
            }
        ),
        encoding="utf-8",
    )
    return d


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model: _FakeModel) -> Path:
    import ultralytics

    monkeypatch.setattr(ultralytics, "YOLO", lambda *args, **kwargs: model)
    out = tmp_path / "out"
    prepare_component_dataset(
        dataset_dir=_make_source_dataset(tmp_path),
        product_manifest=_make_product_manifest(tmp_path, b"product-weights"),
        roi_config=ROIConfig(
            margin_x_ratio=0.05,
            margin_y_ratio=0.05,
            min_area_pixels=1000,
            min_expanded_area_retained=0.80,
        ),
        output_dir=out,
    )
    return out


def test_prepare_keeps_negative_roi_crops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _prepare(tmp_path, monkeypatch, _FakeModel())
    assert (out / "images" / "train" / "img000.png").is_file()
    assert (out / "labels" / "train" / "img000.txt").read_text(encoding="utf-8") == ""
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["train"] == ["img000.png"]
    assert manifest["exclusions"] == {}
    assert json.loads((out / "exclusions.json").read_text(encoding="utf-8")) == {}
    prepared_data = yaml.safe_load((out / "data.yaml").read_text(encoding="utf-8"))
    assert prepared_data["names"] == ["chip"]


def test_prepare_rejects_populated_output_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ultralytics
    from assemblyvision_domain.errors import ConfigError

    monkeypatch.setattr(ultralytics, "YOLO", lambda *args, **kwargs: _FakeModel())
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("old", encoding="utf-8")
    with pytest.raises(ConfigError, match="not empty"):
        prepare_component_dataset(
            dataset_dir=_make_source_dataset(tmp_path),
            product_manifest=_make_product_manifest(tmp_path, b"product-weights"),
            roi_config=ROIConfig(
                margin_x_ratio=0.05,
                margin_y_ratio=0.05,
                min_area_pixels=1000,
                min_expanded_area_retained=0.80,
            ),
            output_dir=out,
        )


def test_prepare_records_multiple_products_as_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _FakeModel(
        _Result(
            [[40.0, 30.0, 160.0, 120.0], [10.0, 10.0, 40.0, 40.0]],
            cls=[0, 0],
            conf=[0.9, 0.8],
        )
    )
    out = _prepare(tmp_path, monkeypatch, model)
    assert not (out / "images" / "train" / "img000.png").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["exclusions"]["train/img000.png"]["reason"] == "NO_PRODUCT_OR_AMBIGUOUS"
    exclusions = json.loads((out / "exclusions.json").read_text(encoding="utf-8"))
    assert exclusions["train/img000.png"]["reason"] == "NO_PRODUCT_OR_AMBIGUOUS"


def test_prepare_records_no_product_as_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _FakeModel(_Result([[40.0, 30.0, 160.0, 120.0]], cls=[1]))
    out = _prepare(tmp_path, monkeypatch, model)
    assert not (out / "images" / "train" / "img000.png").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["exclusions"]["train/img000.png"]["reason"] == "NO_PRODUCT_OR_AMBIGUOUS"


def test_prepare_cleans_staging_output_after_late_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ultralytics

    monkeypatch.setattr(ultralytics, "YOLO", lambda *args, **kwargs: _FakeModel())

    def fail_remap(*args: object) -> list[str]:
        raise RuntimeError("late remap failure")

    monkeypatch.setattr("assemblyvision_training.prepare_components._remap_labels", fail_remap)
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="late remap failure"):
        prepare_component_dataset(
            dataset_dir=_make_source_dataset(tmp_path),
            product_manifest=_make_product_manifest(tmp_path, b"product-weights"),
            roi_config=ROIConfig(
                margin_x_ratio=0.05,
                margin_y_ratio=0.05,
                min_area_pixels=1000,
                min_expanded_area_retained=0.80,
            ),
            output_dir=out,
        )
    assert not out.exists()
    assert list(tmp_path.glob(".out.staging-*")) == []
