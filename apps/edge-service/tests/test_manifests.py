"""Tests for model manifest verification and version binding."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_domain.models import Artifact, ModelManifest
from assemblyvision_edge.config import validate_model_version_declaration
from assemblyvision_vision.manifests import (
    load_model_manifest,
    manifest_model_version,
    model_version_label,
    verify_manifest_artifact,
    verify_model_class_map,
)

from tests.conftest import COMPONENT_MANIFEST


def _weights(tmp_path: Path, data: bytes = b"weights-bytes") -> tuple[Path, str]:
    path = tmp_path / "model.pt"
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def _manifest(weights_path: Path, sha: str, size: int) -> ModelManifest:
    return ModelManifest(
        model_version_id=uuid4(),
        model_id=uuid4(),
        semantic_version="1.0.0",
        model_version_label="component-yolo-1.0.0",
        task="COMPONENT_DETECTION",
        runtime="ultralytics",
        input_width=640,
        input_height=640,
        class_names=["component_a"],
        artifacts=[Artifact(name="weights", uri=weights_path.name, sha256=sha, size_bytes=size)],
        datasets=[],
        split_strategy="by_capture_session",
        source_revision="test",
        training_config_revision="test",
        metrics=[],
        limitations=[],
        approved_by=None,
        approved_at=None,
        supersedes_model_version_id=None,
        created_at=datetime.now(UTC),
    )


def test_verify_manifest_artifact_passes(tmp_path: Path) -> None:
    weights, sha = _weights(tmp_path)
    manifest = _manifest(weights, sha, weights.stat().st_size)
    assert verify_manifest_artifact(manifest, tmp_path / "manifest.json") == weights


def test_verify_manifest_artifact_rejects_checksum_mismatch(tmp_path: Path) -> None:
    weights, _ = _weights(tmp_path)
    manifest = _manifest(weights, "0" * 64, weights.stat().st_size)
    with pytest.raises(ConfigError, match="checksum mismatch"):
        verify_manifest_artifact(manifest, tmp_path / "manifest.json")


def test_verify_manifest_artifact_rejects_size_mismatch(tmp_path: Path) -> None:
    weights, sha = _weights(tmp_path)
    manifest = _manifest(weights, sha, weights.stat().st_size + 1)
    with pytest.raises(ConfigError, match="size mismatch"):
        verify_manifest_artifact(manifest, tmp_path / "manifest.json")


def test_verify_manifest_artifact_rejects_absolute_uri(tmp_path: Path) -> None:
    weights, sha = _weights(tmp_path)
    manifest = _manifest(weights, sha, weights.stat().st_size)
    manifest.artifacts[0].uri = "/etc/passwd"
    with pytest.raises(ConfigError, match="must be relative"):
        verify_manifest_artifact(manifest, tmp_path / "manifest.json")


def test_verify_model_class_map_passes_for_dict_and_mismatch() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    verify_model_class_map({0: "component_a", 1: "component_b", 2: "manual"}, manifest)
    with pytest.raises(ConfigError, match="class map"):
        verify_model_class_map({0: "component_b", 1: "component_a", 2: "manual"}, manifest)
    with pytest.raises(ConfigError, match="class map"):
        verify_model_class_map({0: "component_a", 1: "component_b"}, manifest)


def test_model_version_label_derivation() -> None:
    assert model_version_label("PRODUCT_DETECTION", "1.2.3") == "product-yolo-1.2.3"
    assert model_version_label("COMPONENT_DETECTION", "0.1.0") == "component-yolo-0.1.0"


def test_manifest_model_version_falls_back_to_derived_label() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST).model_copy(
        update={"model_version_label": None}
    )
    assert manifest_model_version(manifest) == "component-yolo-1.0.0"


def test_validate_model_version_declaration_binds_manifest() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    validate_model_version_declaration(
        "component-yolo-1.0.0", manifest, "component_detection.model_version"
    )
    with pytest.raises(ConfigError, match="does not match loaded manifest version"):
        validate_model_version_declaration(
            "component-yolo-9.9.9", manifest, "component_detection.model_version"
        )


def test_load_manifest_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot load model manifest"):
        load_model_manifest(path)


def test_load_manifest_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot load model manifest"):
        load_model_manifest(tmp_path / "missing.json")


def test_model_version_label_rejects_unknown_task() -> None:
    with pytest.raises(ConfigError, match="cannot derive"):
        model_version_label("SEGMENTATION", "1.0.0")


def test_verify_manifest_artifact_rejects_missing_weights(tmp_path: Path) -> None:
    weights, sha = _weights(tmp_path)
    manifest = _manifest(weights, sha, weights.stat().st_size)
    manifest.artifacts[0].uri = "missing.pt"
    with pytest.raises(ConfigError, match="model weights not found"):
        verify_manifest_artifact(manifest, tmp_path / "manifest.json")


def test_verify_manifest_artifact_rejects_no_artifacts(tmp_path: Path) -> None:
    weights, sha = _weights(tmp_path)
    manifest = _manifest(weights, sha, weights.stat().st_size)
    manifest.artifacts = []
    with pytest.raises(ConfigError, match="no artifacts"):
        verify_manifest_artifact(manifest, tmp_path / "manifest.json")


def test_load_manifest_rejects_invalid_content(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid model manifest"):
        load_model_manifest(path)


def test_verify_manifest_artifact_surfaces_stat_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights, sha = _weights(tmp_path)
    manifest = _manifest(weights, sha, weights.stat().st_size)

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "stat", lambda self: (_ for _ in ()).throw(OSError("stat failed")))
    with pytest.raises(ConfigError, match="cannot stat model weights"):
        verify_manifest_artifact(manifest, tmp_path / "manifest.json")


def test_verify_model_class_map_sequence_and_mismatch() -> None:
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    verify_model_class_map(["component_a", "component_b", "manual"], manifest)
    with pytest.raises(ConfigError, match="class map"):
        verify_model_class_map(["component_b", "component_a", "manual"], manifest)
