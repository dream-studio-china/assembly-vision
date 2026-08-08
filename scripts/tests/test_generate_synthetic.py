"""Tests for the procedural synthetic dataset generator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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
