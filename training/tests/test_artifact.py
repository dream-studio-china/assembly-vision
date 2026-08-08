"""Tests for versioned model artifact publication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from assemblyvision_domain.errors import ConfigError
from assemblyvision_training.artifact import place_weights, write_manifest, write_run_metadata
from assemblyvision_vision.manifests import verify_manifest_artifact


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


def test_written_manifest_resolves_documented_sibling_weights_layout(tmp_path: Path) -> None:
    weights = tmp_path / "models" / "weights" / "model.pt"
    manifest_path = tmp_path / "models" / "manifests" / "manifest.json"
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"model")
    manifest = write_manifest(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        class_names=["product"],
        weights_path=weights,
        imgsz=640,
        output_path=manifest_path,
    )
    assert manifest.artifacts[0].uri == "../weights/model.pt"
    assert verify_manifest_artifact(manifest, manifest_path) == weights


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


def _make_dataset(tmp_path: Path) -> Path:
    d = tmp_path / "dataset"
    (d / "images" / "train").mkdir(parents=True)
    (d / "images" / "val").mkdir(parents=True)
    (d / "data.yaml").write_text(yaml.dump({"nc": 1, "names": ["product"]}), encoding="utf-8")
    return d


def test_write_run_metadata_records_reproducibility(tmp_path: Path) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"model")
    dataset = _make_dataset(tmp_path)
    run_path = tmp_path / "model.run.json"
    write_run_metadata(
        task="PRODUCT_DETECTION",
        semantic_version="1.0.0",
        dataset_dir=dataset,
        weights_path=weights,
        epochs=50,
        imgsz=640,
        seed=7,
        model_size="n",
        device="cpu",
        no_augment=True,
        output_path=run_path,
    )
    data = json.loads(run_path.read_text(encoding="utf-8"))
    for key in (
        "task",
        "semantic_version",
        "dataset_dir",
        "dataset_data_yaml_sha256",
        "epochs",
        "imgsz",
        "seed",
        "model_size",
        "augmentations_disabled",
        "device",
        "weights_sha256",
        "weights_size_bytes",
        "python_version",
        "ultralytics_version",
        "created_at",
    ):
        assert key in data, f"missing run metadata key {key}"
    assert data["epochs"] == 50
    assert data["seed"] == 7
    assert data["imgsz"] == 640
    assert data["augmentations_disabled"] is True
    assert len(data["dataset_data_yaml_sha256"]) == 64
    assert len(data["weights_sha256"]) == 64


def test_write_run_metadata_is_idempotent_and_refuses_different_content(
    tmp_path: Path,
) -> None:
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"model")
    dataset = _make_dataset(tmp_path)
    run_path = tmp_path / "model.run.json"

    def write() -> None:
        write_run_metadata(
            task="PRODUCT_DETECTION",
            semantic_version="1.0.0",
            dataset_dir=dataset,
            weights_path=weights,
            epochs=50,
            imgsz=640,
            seed=7,
            model_size="n",
            device="cpu",
            no_augment=True,
            output_path=run_path,
        )

    write()
    write()  # identical rerun is a no-op
    weights.write_bytes(b"model-v2")
    with pytest.raises(ConfigError, match="refusing to overwrite existing run metadata"):
        write()
