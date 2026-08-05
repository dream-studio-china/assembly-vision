"""Tests for component dataset preparation (pure remap logic)."""

from __future__ import annotations

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


class _Boxes:
    def __init__(self, box: list[float]) -> None:
        self.xyxy = [_Tensor(box)]

    def __len__(self) -> int:
        return 1


class _Result:
    def __init__(self, box: list[float]) -> None:
        self.boxes = _Boxes(box)


class _FakeModel:
    def __call__(
        self, frame: Image.Image, verbose: bool = False, conf: float = 0.1
    ) -> list[_Result]:
        return [_Result([40.0, 30.0, 160.0, 120.0])]


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


def test_prepare_keeps_negative_roi_crops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ultralytics

    monkeypatch.setattr(ultralytics, "YOLO", lambda *args, **kwargs: _FakeModel())
    out = tmp_path / "out"
    prepare_component_dataset(
        dataset_dir=_make_source_dataset(tmp_path),
        product_weights=tmp_path / "product.pt",
        roi_config=ROIConfig(
            margin_x_ratio=0.05,
            margin_y_ratio=0.05,
            min_area_pixels=1000,
            min_expanded_area_retained=0.80,
        ),
        output_dir=out,
    )
    assert (out / "images" / "train" / "img000.png").is_file()
    assert (out / "labels" / "train" / "img000.txt").read_text(encoding="utf-8") == ""
