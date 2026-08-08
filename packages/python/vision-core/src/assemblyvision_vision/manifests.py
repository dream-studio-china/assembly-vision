"""Model manifest loading and validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from assemblyvision_domain.errors import ConfigError
from assemblyvision_domain.models import ModelManifest

_MODEL_TASK_LABEL_PREFIX = {
    "PRODUCT_DETECTION": "product-yolo",
    "COMPONENT_DETECTION": "component-yolo",
}


def load_model_manifest(path: Path) -> ModelManifest:
    """Load and validate a model manifest JSON file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot load model manifest: {path}: {exc}") from exc
    try:
        manifest = ModelManifest.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"invalid model manifest {path}: {exc}") from exc
    if manifest.runtime != "ultralytics":
        raise ConfigError(
            f"unsupported model runtime {manifest.runtime!r} in {path}: "
            "only 'ultralytics' is supported"
        )
    return manifest


def model_version_label(task: str, semantic_version: str) -> str:
    """Derive the canonical rule-facing model version label for a task."""
    prefix = _MODEL_TASK_LABEL_PREFIX.get(task)
    if prefix is None:
        raise ConfigError(f"cannot derive a model version label for task {task!r}")
    return f"{prefix}-{semantic_version}"


def manifest_model_version(manifest: ModelManifest) -> str:
    """Return the canonical model version label recorded in a manifest."""
    if manifest.model_version_label:
        return manifest.model_version_label
    return model_version_label(manifest.task, manifest.semantic_version)


def verify_manifest_artifact(manifest: ModelManifest, manifest_path: Path) -> Path:
    """Resolve and verify the primary artifact (size and SHA-256) of a manifest.

    Fails on any mismatch so a tampered, stale, or wrongly paired artifact
    can never reach inference. The artifact URI must be relative to the
    manifest directory and resolve within the model bundle root (the manifest
    directory's parent): absolute paths, URI schemes, and paths that escape
    the bundle root (including via symlinks) are rejected. This permits the
    documented ``models/manifests`` and sibling ``models/weights`` layout.
    """
    if not manifest.artifacts:
        raise ConfigError(f"model manifest {manifest_path} has no artifacts")
    artifact = manifest.artifacts[0]
    uri = artifact.uri
    if uri.startswith(("/", "\\")):
        raise ConfigError(f"model artifact uri must be relative to the manifest: {uri!r}")
    if "://" in uri:
        raise ConfigError(f"model artifact uri must not use a scheme: {uri!r}")
    parts = Path(uri).parts
    if any(len(part) == 2 and part.endswith(":") for part in parts):
        raise ConfigError(f"model artifact uri must not contain a drive segment: {uri!r}")
    manifest_dir = manifest_path.parent.resolve()
    bundle_root = manifest_dir.parent
    path = (manifest_dir / uri).resolve()
    if not path.is_relative_to(bundle_root):
        raise ConfigError(f"model artifact uri escapes the model bundle: {uri!r}")
    if not path.is_file():
        raise ConfigError(f"model weights not found: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ConfigError(f"cannot stat model weights {path}") from exc
    if size != artifact.size_bytes:
        raise ConfigError(
            f"model weights size mismatch for {path}: expected {artifact.size_bytes}, got {size}"
        )
    digest = sha256_file(path)
    if digest != artifact.sha256:
        raise ConfigError(
            f"model weights checksum mismatch for {path}: expected {artifact.sha256}, got {digest}"
        )
    return path


def verify_model_class_map(
    names: Mapping[int, object] | Sequence[object], manifest: ModelManifest
) -> None:
    """Validate the loaded model's class map against the manifest class order.

    Ultralytics exposes ``model.names`` as a ``{class_id: name}`` mapping; the
    class ID ordering is part of the trained artifact and must match the
    manifest so results are interpreted with the correct class names.
    """
    if isinstance(names, Mapping):
        try:
            ordered = [str(names[i]) for i in range(len(names))]
        except (KeyError, IndexError) as exc:
            raise ConfigError(
                f"model class map is not contiguous: expected keys 0..{len(names) - 1}: {exc}"
            ) from exc
    else:
        ordered = [str(n) for n in names]
    if ordered != manifest.class_names:
        raise ConfigError(
            f"model class map {ordered!r} does not match manifest class_names {manifest.class_names!r}"
        )


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
