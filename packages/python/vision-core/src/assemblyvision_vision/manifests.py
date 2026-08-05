"""Model manifest loading and validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from assemblyvision_domain.errors import ConfigError
from assemblyvision_domain.models import ModelManifest


def load_model_manifest(path: Path) -> ModelManifest:
    """Load and validate a model manifest JSON file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot load model manifest: {path}: {exc}") from exc
    try:
        return ModelManifest.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"invalid model manifest {path}: {exc}") from exc


def resolve_artifact_path(manifest: ModelManifest, manifest_path: Path) -> Path:
    """Resolve the first model artifact path relative to the manifest file."""
    if not manifest.artifacts:
        raise ConfigError(f"model manifest {manifest_path} has no artifacts")
    uri = manifest.artifacts[0].uri
    path = Path(uri)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
