"""Tests for the procedural synthetic dataset generator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_SCRIPT = Path(__file__).resolve().parents[1] / "generate-synthetic-dataset.py"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_synthetic_dataset", _SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = _load_generator()


def test_generated_data_yaml_uses_portable_relative_paths(tmp_path: Path) -> None:
    out = tmp_path / "out"
    generator.generate(out, n_train=2, n_val=2)

    for data_yaml in (
        out / "dataset_product" / "data.yaml",
        out / "dataset_components" / "data.yaml",
    ):
        data = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
        assert data["train"] == "images/train"
        assert data["val"] == "images/val"
        for key in ("train", "val"):
            resolved = (data_yaml.parent / data[key]).resolve()
            assert resolved.is_dir(), f"{key} path {data[key]} is not a directory"
            assert list(resolved.iterdir()), f"{key} directory {resolved} is empty"
            assert ".staging-" not in str(data[key])


def _rotated_aabb_identity() -> tuple[float, float, float, float]:
    # rotation 0 keeps the rectangle unchanged
    return generator._rotated_aabb(10.0, 20.0, 30.0, 40.0, 20.0, 30.0, 0.0)


def test_rotated_aabb_is_axis_aligned_and_contains_rotated_corners() -> None:
    x1, y1, x2, y2 = 10.0, 20.0, 30.0, 40.0
    cx, cy = 20.0, 30.0
    rad = 0.05
    ax1, ay1, ax2, ay2 = generator._rotated_aabb(x1, y1, x2, y2, cx, cy, rad)
    assert ax1 <= x1 and ay1 <= y1 and ax2 >= x2 and ay2 >= y2
    for px, py in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
        rx, ry = generator._rotated_point(px, py, cx, cy, rad)
        assert ax1 <= rx <= ax2 and ay1 <= ry <= ay2


def test_labels_match_unrotated_geometry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force rotation 0 so the label must equal the unrotated component rect.
    monkeypatch.setattr(generator.random, "choice", lambda seq: 0)
    out = tmp_path / "out"
    generator.generate(out, n_train=1, n_val=1)

    label_path = out / "dataset_components" / "labels" / "train" / "img000.txt"
    lines = label_path.read_text(encoding="utf-8").strip().splitlines()
    names = list(generator.COMPONENTS)
    assert len(lines) == len(names)  # img000 has every component present
    for line in lines:
        cls_id = int(line.split()[0])
        code = names[cls_id]
        x1, y1, x2, y2 = generator.COMPONENTS[code]
        cx, cy, w, h = (float(v) for v in line.split()[1:])
        # Width/height are unaffected by the shift and must match the rect.
        assert w == pytest.approx((x2 - x1) / generator.IMG_W, abs=1e-3)
        assert h == pytest.approx((y2 - y1) / generator.IMG_H, abs=1e-3)
        # The center may only move within the documented jitter range.
        assert abs(cx * generator.IMG_W - (x1 + x2) / 2) <= 24
        assert abs(cy * generator.IMG_H - (y1 + y2) / 2) <= 18


def test_every_missing_scenario_occurs_in_training(tmp_path: Path) -> None:
    out = tmp_path / "out"
    generator.generate(out, n_train=16, n_val=2)

    names = list(generator.COMPONENTS)
    absent: dict[str, bool] = dict.fromkeys(names, False)
    any_all_present = False
    for label_path in sorted((out / "dataset_components" / "labels" / "train").glob("*.txt")):
        codes = {names[int(line.split()[0])] for line in label_path.read_text().splitlines()}
        for code in names:
            if code not in codes:
                absent[code] = True
        if codes == set(names):
            any_all_present = True
    assert absent == dict.fromkeys(names, True)
    assert any_all_present
