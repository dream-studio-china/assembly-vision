"""Shared test helpers for the training tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def yolo_dataset_dir(tmp_path: Path) -> Path:
    """Create a minimal valid YOLO dataset with synthetic images and labels."""
    from PIL import Image

    d = tmp_path / "dataset"
    for split in ("train", "val"):
        (d / "images" / split).mkdir(parents=True)
        (d / "labels" / split).mkdir(parents=True)

    class_names = ["product"]

    for i in range(4):
        split = "train" if i < 3 else "val"
        img = Image.new("RGB", (64, 64), (128 + i * 30, 128, 128))
        img.save(d / "images" / split / f"img{i:03d}.png")
        label = d / "labels" / split / f"img{i:03d}.txt"
        label.write_text(f"0 {0.5} {0.5} {0.6} {0.6}\n", encoding="utf-8")

    data = {
        "nc": 1,
        "names": class_names,
        "train": str((d / "images" / "train").resolve()),
        "val": str((d / "images" / "val").resolve()),
    }
    (d / "data.yaml").write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return d
