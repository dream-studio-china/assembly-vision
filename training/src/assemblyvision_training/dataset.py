"""YOLO dataset layout validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from assemblyvision_domain.errors import ConfigError

SUPPORTED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"})


@dataclass(frozen=True)
class DatasetInfo:
    """Validated YOLO dataset metadata."""

    path: Path
    class_names: list[str]
    train_images: int = 0
    val_images: int = 0
    train_labeled: int = 0
    val_labeled: int = 0
    warnings: list[str] = field(default_factory=list)


def validate_dataset(dataset_dir: Path) -> DatasetInfo:
    """Validate a YOLO-format dataset directory and return metadata."""
    if not dataset_dir.is_dir():
        raise ConfigError(f"dataset directory does not exist: {dataset_dir}")

    data_yaml = dataset_dir / "data.yaml"
    if not data_yaml.is_file():
        raise ConfigError(f"missing data.yaml in dataset: {dataset_dir}")

    try:
        raw = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot parse data.yaml: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("data.yaml must be a mapping")

    class_names: list[str] = raw.get("names", [])
    if not isinstance(class_names, list) or not class_names:
        raise ConfigError("data.yaml names must be a non-empty list")

    nc = raw.get("nc", 0)
    if not isinstance(nc, int) or nc <= 0:
        raise ConfigError("data.yaml nc must be a positive integer")
    if nc != len(class_names):
        raise ConfigError(f"data.yaml nc={nc} does not match len(names)={len(class_names)}")

    info = DatasetInfo(
        path=dataset_dir,
        class_names=[str(n) for n in class_names],
    )

    for split, _attr_prefix, img_key, lbl_key in [
        ("train", "train", "train", "train"),
        ("val", "val", "val", "val"),
    ]:
        img_dir = dataset_dir / "images" / img_key
        lbl_dir = dataset_dir / "labels" / lbl_key

        if not img_dir.is_dir():
            info.warnings.append(f"images/{img_key} is not a directory; skipping")
            continue

        image_count = 0
        labeled_count = 0

        for img_path in sorted(img_dir.iterdir()):
            if not img_path.is_file() or img_path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            image_count += 1
            lbl_path = lbl_dir / f"{img_path.stem}.txt"
            if lbl_path.is_file():
                try:
                    _validate_label_file(lbl_path, nc, img_path)
                except ConfigError as exc:
                    info.warnings.append(f"{lbl_path.name}: {exc}")
                    continue
                labeled_count += 1
            else:
                info.warnings.append(f"no label file for {img_path.name}")

        if split == "train":
            info = DatasetInfo(
                path=info.path,
                class_names=info.class_names,
                train_images=image_count,
                val_images=info.val_images,
                train_labeled=labeled_count,
                val_labeled=info.val_labeled,
                warnings=info.warnings,
            )
        else:
            info = DatasetInfo(
                path=info.path,
                class_names=info.class_names,
                train_images=info.train_images,
                val_images=image_count,
                train_labeled=info.train_labeled,
                val_labeled=labeled_count,
                warnings=info.warnings,
            )

    if info.train_images == 0:
        raise ConfigError("dataset has no training images in images/train/")
    return info


def _validate_label_file(path: Path, nc: int, img_path: Path) -> None:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ConfigError(f"line {lineno}: expected 5 fields, got {len(parts)}")
        try:
            cls_id = int(parts[0])
            cx, cy, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        except ValueError as exc:
            raise ConfigError(f"line {lineno}: invalid numeric value: {exc}") from exc
        if not (0 <= cls_id < nc):
            raise ConfigError(f"line {lineno}: class id {cls_id} out of range [0, {nc - 1}]")
        for name, val in [("cx", cx), ("cy", cy), ("w", w), ("h", h)]:
            if not (0.0 <= val <= 1.0):
                raise ConfigError(f"line {lineno}: {name}={val} is not normalized")
