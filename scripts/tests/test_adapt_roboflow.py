"""Tests for the Roboflow dataset adapter."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from PIL import Image

_SCRIPT = Path(__file__).resolve().parents[1] / "adapt-roboflow-dataset.py"


def _load_adapter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("adapt_roboflow_dataset", _SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()
adapt = adapter.adapt


def _make_export(tmp_path: Path, splits: list[str]) -> Path:
    """Build a small Roboflow-style export with product + component classes."""
    src = tmp_path / "roboflow"
    for split in splits:
        (src / "images" / split).mkdir(parents=True)
        (src / "labels" / split).mkdir(parents=True)
    for i, split in enumerate(splits):
        img = Image.new("RGB", (200, 150), (i * 30, 128, 128))
        img.save(src / "images" / split / f"img_{split}_{i}.png")
    names = ["product", "chip", "capacitor", "missing_chip"]
    (src / "data.yaml").write_text(yaml.dump({"nc": len(names), "names": names}), encoding="utf-8")
    return src


def _labels(src: Path, split: str, stem: str) -> Path:
    return src / "labels" / split / f"{stem}.txt"


def test_adapter_rejects_missing_product_class(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "images" / "train").mkdir(parents=True)
    (src / "data.yaml").write_text(yaml.dump({"nc": 1, "names": ["chip"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="no product class"):
        adapt(src, tmp_path / "out", required=["chip"], product_class="product")


def test_adapter_rejects_missing_required_class(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    with pytest.raises(ValueError, match="required component classes not present"):
        adapt(src, tmp_path / "out", required=["chip", "boot"], product_class="product")


def test_adapter_drops_missing_classes_and_builds_expected(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val", "test"])
    # test image has chip only -> NG (capacitor missing)
    _labels(src, "test", "img_test_2").write_text("1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    out = tmp_path / "out"
    adapt(src, out, required=["chip", "capacitor"], product_class="product")

    comp_names = yaml.safe_load((out / "dataset_components" / "data.yaml").read_text())["names"]
    assert comp_names == ["chip", "capacitor"]
    product_names = yaml.safe_load((out / "dataset_product" / "data.yaml").read_text())["names"]
    assert product_names == ["product"]

    expected = json.loads((out / "test-expected.json").read_text(encoding="utf-8"))
    assert expected["img_test_2.png"]["ok"] is False
    assert expected["img_test_2.png"]["present"] == ["chip"]
    assert expected["img_test_2.png"]["missing"] == ["capacitor"]
    # test image must exist only under out/test, not under any training split
    assert (out / "test" / "img_test_2.png").is_file()
    assert not (out / "dataset_components" / "images" / "val" / "img_test_2.png").exists()
    assert not (out / "dataset_product" / "images" / "val" / "img_test_2.png").exists()


def test_adapter_uses_independent_product_box_not_component_union(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    # product box present and independent of component boxes
    _labels(src, "train", "img_train_0").write_text(
        "0 0.5 0.5 0.8 0.8\n1 0.5 0.5 0.2 0.2\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    adapt(src, out, required=["chip", "capacitor"], product_class="product")

    product_label = (
        (out / "dataset_product" / "labels" / "train" / "img_train_0.txt").read_text().strip()
    )
    cx, cy, w, h = (float(v) for v in product_label.split()[1:])
    # the product box reflects the annotated full product, not the component size
    assert w == pytest.approx(0.8, abs=1e-3)
    assert h == pytest.approx(0.8, abs=1e-3)


def test_adapter_skips_product_images_without_product_box(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    # chip annotation only, no product box
    _labels(src, "train", "img_train_0").write_text("1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="no 'product' product box"):
        adapt(src, out, required=["chip", "capacitor"], product_class="product")
    assert not out.exists()
    assert list(tmp_path.glob(".out.staging-*")) == []


def test_adapter_rejects_negative_class_id(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    _labels(src, "train", "img_train_0").write_text("-1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="class id -1 out of range"):
        adapt(src, tmp_path / "out", required=["chip", "capacitor"], product_class="product")


def test_adapter_rejects_wrong_field_count(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    _labels(src, "train", "img_train_0").write_text("0 0.5 0.5 0.2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected 5 fields"):
        adapt(src, tmp_path / "out", required=["chip", "capacitor"], product_class="product")


def test_adapter_rejects_non_finite_coordinates(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    _labels(src, "train", "img_train_0").write_text("0 0.5 0.5 nan 0.2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="coordinates must be finite"):
        adapt(src, tmp_path / "out", required=["chip", "capacitor"], product_class="product")


def test_adapter_rejects_box_outside_image(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    _labels(src, "train", "img_train_0").write_text("0 0.02 0.5 0.1 0.3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the image bounds"):
        adapt(src, tmp_path / "out", required=["chip", "capacitor"], product_class="product")


def test_adapter_keeps_background_negatives_in_product_dataset(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    _labels(src, "train", "img_train_0").write_text("", encoding="utf-8")
    out = tmp_path / "out"
    adapt(src, out, required=["chip", "capacitor"], product_class="product")

    # An explicit empty-label image is a background negative, kept in the
    # product dataset with an empty product label file.
    assert (out / "dataset_product" / "images" / "train" / "img_train_0.png").is_file()
    assert (out / "dataset_product" / "labels" / "train" / "img_train_0.txt").read_text(
        encoding="utf-8"
    ) == ""


def test_adapter_rejects_populated_output(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("old", encoding="utf-8")
    with pytest.raises(ValueError, match="not empty"):
        adapt(src, out, required=["chip", "capacitor"], product_class="product")


def test_adapter_writes_file_manifest(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val"])
    out = tmp_path / "out"
    adapt(src, out, required=["chip", "capacitor"], product_class="product")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["product_class"] == "product"
    assert "train/img_train_0.png" in manifest["files"]["product"]
    assert "train/img_train_0.png" in manifest["files"]["components"]
    assert manifest["product_background_negatives"]["train"] >= 1


def test_adapter_detects_held_out_overlap_with_validation(tmp_path: Path) -> None:
    src = _make_export(tmp_path, ["train", "val", "test"])
    # make the test image byte-identical to a validation image
    test_bytes = (src / "images" / "test" / "img_test_2.png").read_bytes()
    (src / "images" / "val" / "img_val_1.png").write_bytes(test_bytes)
    with pytest.raises(ValueError, match="overlap"):
        adapt(src, tmp_path / "out", required=["chip", "capacitor"], product_class="product")
