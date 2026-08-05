"""Tests for YOLO dataset validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_training.dataset import validate_dataset


def test_valid_dataset_passes(yolo_dataset_dir: Path) -> None:
    info = validate_dataset(yolo_dataset_dir)
    assert info.class_names == ["product"]
    assert info.train_images == 3
    assert info.val_images == 1
    assert info.train_labeled == 3
    assert info.val_labeled == 1


def test_rejects_missing_data_yaml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing data.yaml"):
        validate_dataset(tmp_path)


def test_rejects_mismatched_nc(tmp_path: Path) -> None:
    d = tmp_path / "mismatched"
    d.mkdir()
    (d / "images" / "train").mkdir(parents=True)
    (d / "data.yaml").write_text("nc: 5\nnames: ['a']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="nc=5 does not match"):
        validate_dataset(d)


def test_rejects_no_train_images(tmp_path: Path) -> None:
    d = tmp_path / "empty"
    d.mkdir()
    (d / "images" / "train").mkdir(parents=True)
    (d / "images" / "val").mkdir(parents=True)
    (d / "data.yaml").write_text("nc: 1\nnames: ['a']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no training images"):
        validate_dataset(d)


def test_warns_on_unpaired_images(yolo_dataset_dir: Path) -> None:
    from PIL import Image

    (yolo_dataset_dir / "images" / "train" / "unlabeled.png").touch()
    Image.new("RGB", (64, 64), (100, 100, 100)).save(yolo_dataset_dir / "images" / "train" / "unlabeled.png")
    info = validate_dataset(yolo_dataset_dir)
    assert any("no label" in w for w in info.warnings)


def test_rejects_out_of_range_class(yolo_dataset_dir: Path) -> None:
    (yolo_dataset_dir / "labels" / "train" / "img000.txt").write_text("9 0.5 0.5 0.3 0.3\n")
    with pytest.raises(ConfigError, match="class id 9 out of range"):
        validate_dataset(yolo_dataset_dir)


def test_rejects_unormalized_label(yolo_dataset_dir: Path) -> None:
    (yolo_dataset_dir / "labels" / "train" / "img000.txt").write_text("0 5.0 0.5 0.3 0.3\n")
    with pytest.raises(ConfigError, match="is not normalized"):
        validate_dataset(yolo_dataset_dir)


def test_rejects_zero_sized_box(yolo_dataset_dir: Path) -> None:
    (yolo_dataset_dir / "labels" / "train" / "img000.txt").write_text("0 0.5 0.5 0.0 0.3\n")
    with pytest.raises(ConfigError, match="width and height must be positive"):
        validate_dataset(yolo_dataset_dir)


def test_rejects_box_outside_image(yolo_dataset_dir: Path) -> None:
    (yolo_dataset_dir / "labels" / "train" / "img000.txt").write_text("0 0.02 0.5 0.1 0.3\n")
    with pytest.raises(ConfigError, match="outside the image bounds"):
        validate_dataset(yolo_dataset_dir)


def test_rejects_missing_val_split(tmp_path: Path) -> None:
    d = tmp_path / "no-val"
    (d / "images" / "train").mkdir(parents=True)
    (d / "labels" / "train").mkdir(parents=True)
    from PIL import Image

    Image.new("RGB", (64, 64), (0, 0, 0)).save(d / "images" / "train" / "a.png")
    (d / "labels" / "train" / "a.txt").write_text("0 0.5 0.5 0.3 0.3\n", encoding="utf-8")
    (d / "data.yaml").write_text("nc: 1\nnames: ['a']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no validation images"):
        validate_dataset(d)
