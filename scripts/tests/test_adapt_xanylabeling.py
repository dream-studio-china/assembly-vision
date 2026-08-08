"""Tests for the X-AnyLabeling dataset adapter."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from PIL import Image

_SCRIPT = Path(__file__).resolve().parents[1] / "adapt-xanylabeling.py"


def _load_adapter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("adapt_xanylabeling", _SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()
adapt = adapter.adapt


def _make_export(tmp_path: Path, layout: str = "split-first") -> Path:
    """Build a small X-AnyLabeling YOLO export (product + components).

    Every image gets an explicit empty label file so image/label pairing is
    satisfied; individual tests overwrite specific labels.
    """
    src = tmp_path / "xal"
    for split in ("train", "val", "test"):
        if layout == "split-first":
            (src / split / "images").mkdir(parents=True)
            (src / split / "labels").mkdir(parents=True)
        else:
            (src / "images" / split).mkdir(parents=True)
            (src / "labels" / split).mkdir(parents=True)
    for i, split in enumerate(("train", "val", "test")):
        img = Image.new("RGB", (200, 150), (i * 40, 128, 128))
        img_dir = src / split / "images" if layout == "split-first" else src / "images" / split
        lbl_dir = src / split / "labels" if layout == "split-first" else src / "labels" / split
        img.save(img_dir / f"img_{split}_{i}.png")
        (lbl_dir / f"img_{split}_{i}.txt").write_text("", encoding="utf-8")
    (src / "classes.txt").write_text("product\nchip\ncapacitor\n", encoding="utf-8")
    return src


def _lbl(src: Path, split: str, stem: str, layout: str = "split-first") -> Path:
    if layout == "split-first":
        return src / split / "labels" / f"{stem}.txt"
    return src / "labels" / split / f"{stem}.txt"


def test_adapter_reads_classes_txt_and_builds_two_stage(tmp_path: Path) -> None:
    src = _make_export(tmp_path)
    _lbl(src, "train", "img_train_0").write_text(
        "0 0.5 0.5 0.8 0.8\n1 0.5 0.5 0.2 0.2\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    adapt(src, out, required=["chip", "capacitor"], product_class="product")

    product_names = yaml.safe_load((out / "dataset_product" / "data.yaml").read_text())["names"]
    comp_names = yaml.safe_load((out / "dataset_components" / "data.yaml").read_text())["names"]
    assert product_names == ["product"]
    assert comp_names == ["chip", "capacitor"]
    assert (out / "dataset_product" / "images" / "train" / "img_train_0.png").is_file()
    assert (out / "dataset_components" / "images" / "train" / "img_train_0.png").is_file()


def test_adapter_accepts_images_first_layout(tmp_path: Path) -> None:
    src = _make_export(tmp_path, layout="images-first")
    _lbl(src, "train", "img_train_0", layout="images-first").write_text(
        "0 0.5 0.5 0.8 0.8\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    adapt(src, out, required=["chip"], product_class="product")
    assert (out / "dataset_product" / "images" / "train" / "img_train_0.png").is_file()


def test_adapter_rejects_missing_product_class(tmp_path: Path) -> None:
    src = _make_export(tmp_path)
    (src / "classes.txt").write_text("chip\ncapacitor\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no product class"):
        adapt(src, tmp_path / "out", required=["chip"], product_class="product")


def test_adapter_rejects_component_only_image_without_product_box(tmp_path: Path) -> None:
    src = _make_export(tmp_path)
    _lbl(src, "train", "img_train_0").write_text("1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="no 'product' product box"):
        adapt(src, out, required=["chip"], product_class="product")
    assert not out.exists()
    assert list(tmp_path.glob(".out.staging-*")) == []


def test_adapter_keeps_background_negatives_and_writes_expected(tmp_path: Path) -> None:
    src = _make_export(tmp_path)
    _lbl(src, "train", "img_train_0").write_text("", encoding="utf-8")
    _lbl(src, "test", "img_test_2").write_text("1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    out = tmp_path / "out"
    adapt(src, out, required=["chip", "capacitor"], product_class="product")

    assert (out / "dataset_product" / "labels" / "train" / "img_train_0.txt").read_text() == ""
    expected = json.loads((out / "test-expected.json").read_text(encoding="utf-8"))
    assert expected["img_test_2.png"]["ok"] is False
    assert expected["img_test_2.png"]["missing"] == ["capacitor"]


def test_adapter_rejects_populated_output(tmp_path: Path) -> None:
    src = _make_export(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("old", encoding="utf-8")
    with pytest.raises(ValueError, match="not empty"):
        adapt(src, out, required=["chip"], product_class="product")


@pytest.mark.parametrize("split", ["train", "val", "test"])
def test_adapter_rejects_missing_label_file(tmp_path: Path, split: str) -> None:
    src = _make_export(tmp_path)
    index = {"train": 0, "val": 1, "test": 2}[split]
    (src / split / "labels" / f"img_{split}_{index}.txt").unlink()
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="no label file"):
        adapt(src, out, required=["chip", "capacitor"], product_class="product")
    assert not out.exists()
    assert not (out / "test-expected.json").exists()
    assert list(tmp_path.glob(".out.staging-*")) == []


def test_adapter_accepts_explicit_empty_label_file(tmp_path: Path) -> None:
    src = _make_export(tmp_path)
    out = tmp_path / "out"
    adapt(src, out, required=["chip", "capacitor"], product_class="product")
    assert (out / "dataset_product" / "labels" / "train" / "img_train_0.txt").read_text() == ""


def test_adapter_rejects_stem_collision(tmp_path: Path) -> None:
    src = _make_export(tmp_path)
    (src / "train" / "images" / "img_train_0.jpg").write_bytes(
        (src / "train" / "images" / "img_train_0.png").read_bytes()
    )
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="stem collision"):
        adapt(src, out, required=["chip", "capacitor"], product_class="product")
    assert not out.exists()
    assert list(tmp_path.glob(".out.staging-*")) == []


def test_adapter_rejects_duplicate_canonical_splits(tmp_path: Path) -> None:
    src = _make_export(tmp_path)
    (src / "valid" / "images").mkdir(parents=True)
    (src / "valid" / "labels").mkdir(parents=True)
    img = Image.new("RGB", (200, 150), (90, 90, 90))
    img.save(src / "valid" / "images" / "img_valid_0.png")
    (src / "valid" / "labels" / "img_valid_0.txt").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate canonical splits"):
        adapt(src, tmp_path / "out", required=["chip", "capacitor"], product_class="product")


def _assert_portable_data_yaml(data_yaml: Path) -> None:
    data = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    assert data["train"] == "images/train"
    assert data["val"] == "images/val"
    for key in ("train", "val"):
        resolved = (data_yaml.parent / data[key]).resolve()
        assert resolved.is_dir(), f"{key} path {data[key]} does not exist under the output root"
        assert list(resolved.iterdir()), f"{key} directory {resolved} is empty"


def test_adapter_publishes_portable_data_yaml_paths(tmp_path: Path) -> None:
    src = _make_export(tmp_path)
    out = tmp_path / "out"
    adapt(src, out, required=["chip", "capacitor"], product_class="product")
    _assert_portable_data_yaml(out / "dataset_product" / "data.yaml")
    _assert_portable_data_yaml(out / "dataset_components" / "data.yaml")
