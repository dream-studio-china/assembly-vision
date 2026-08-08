"""Tests for versioned model artifact publication."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_training.artifact import place_weights, write_manifest


def test_place_weights_installs(tmp_path: Path) -> None:
    best = tmp_path / "best.pt"
    best.write_bytes(b"model")
    target = tmp_path / "weights" / "model.pt"
    place_weights(best, target)
    assert target.read_bytes() == b"model"


def test_place_weights_accepts_identical_bytes(tmp_path: Path) -> None:
    best = tmp_path / "best.pt"
    best.write_bytes(b"model")
    target = tmp_path / "model.pt"
    target.write_bytes(b"model")
    place_weights(best, target)
    assert target.read_bytes() == b"model"


def test_place_weights_refuses_different_bytes(tmp_path: Path) -> None:
    best = tmp_path / "best.pt"
    best.write_bytes(b"model-v2")
    target = tmp_path / "model.pt"
    target.write_bytes(b"model-v1")
    with pytest.raises(ConfigError, match="refusing to overwrite"):
        place_weights(best, target)


def test_write_manifest_rejects_invalid_semver(tmp_path: Path) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"model")
    with pytest.raises(ConfigError, match="X.Y.Z"):
        write_manifest(
            task="PRODUCT_DETECTION",
            semantic_version="not-a-version",
            class_names=["product"],
            weights_path=weights,
            imgsz=640,
            output_path=tmp_path / "manifest.json",
        )


def test_write_manifest_overwrites_identical_artifact(tmp_path: Path) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"model")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    assert manifest_path.is_file()


def test_write_manifest_refuses_different_artifact(tmp_path: Path) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"model-v1")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    weights.write_bytes(b"model-v2")
    with pytest.raises(ConfigError, match="refusing to overwrite existing manifest"):
        write_manifest(
            task="PRODUCT_DETECTION",
            semantic_version="1.0.0",
            class_names=["product"],
            weights_path=weights,
            imgsz=640,
            output_path=manifest_path,
        )


def test_write_manifest_refuses_changed_class_order(tmp_path: Path) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"model")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    with pytest.raises(ConfigError, match="decision-critical content differs"):
        write_manifest(
            task="PRODUCT_DETECTION",
            semantic_version="1.0.0",
            class_names=["other", "product"],
            weights_path=weights,
            imgsz=640,
            output_path=manifest_path,
        )


def test_write_manifest_refuses_changed_task(tmp_path: Path) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"model")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    with pytest.raises(ConfigError, match="decision-critical content differs"):
        write_manifest(
            task="COMPONENT_DETECTION",
            semantic_version="1.0.0",
            class_names=["product"],
            weights_path=weights,
            imgsz=640,
            output_path=manifest_path,
        )


def test_write_manifest_refuses_changed_input_size(tmp_path: Path) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"model")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    with pytest.raises(ConfigError, match="decision-critical content differs"):
        write_manifest(
            task="PRODUCT_DETECTION",
            semantic_version="1.0.0",
            class_names=["product"],
            weights_path=weights,
            imgsz=1280,
            output_path=manifest_path,
        )


def test_write_manifest_identical_republication_is_idempotent(tmp_path: Path) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"model")
    manifest_path = tmp_path / "manifest.json"
    first = write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    before = manifest_path.read_text(encoding="utf-8")
    second = write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    # The existing manifest is returned without being rewritten.
    assert second.model_version_id == first.model_version_id
    assert manifest_path.read_text(encoding="utf-8") == before
