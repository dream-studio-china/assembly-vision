"""Model artifact writer: weights checksum and manifest JSON."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from assemblyvision_domain.errors import ConfigError
from assemblyvision_domain.models import Artifact, ModelManifest

_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def place_weights(best: Path, weights_path: Path) -> None:
    """Install trained weights, refusing to replace a different artifact.

    Re-running a training that produces identical bytes is idempotent;
    replacing an existing versioned artifact with different bytes would
    silently change the model behind a published version identity.
    """
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    if weights_path.exists():
        if sha256_file(weights_path) == sha256_file(best):
            return
        raise ConfigError(
            f"refusing to overwrite existing weights {weights_path} with different bytes; "
            "bump --semver or remove the file"
        )
    best.replace(weights_path)


def _reject_existing_manifest_overwrite(path: Path, new_checksum: str, semantic_version: str) -> None:
    try:
        existing = ModelManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"existing manifest {path} is invalid; refusing to overwrite: {exc}") from exc
    if (
        existing.semantic_version == semantic_version
        and existing.artifacts
        and existing.artifacts[0].sha256 == new_checksum
    ):
        return
    raise ConfigError(
        f"refusing to overwrite existing manifest {path} with a different artifact; "
        "bump --semver or remove the file"
    )


def write_manifest(
    *,
    task: str,
    semantic_version: str,
    class_names: list[str],
    weights_path: Path,
    imgsz: int,
    output_path: Path,
) -> ModelManifest:
    """Write a versioned model manifest JSON file and return the manifest.

    ``weights_uri`` is stored relative to the manifest directory so the
    manifest stays portable. An existing manifest for the same semantic
    version is only preserved when it references the identical artifact;
    otherwise publication is refused so versioned identities stay immutable.
    """
    if not _SEMVER_RE.match(semantic_version):
        raise ConfigError(
            f"semantic_version {semantic_version!r} is not a valid X.Y.Z version"
        )
    checksum = sha256_file(weights_path)
    size = weights_path.stat().st_size
    relative_uri = os.path.relpath(
        Path(weights_path).resolve(), output_path.parent.resolve()
    )

    artifact = Artifact(
        name="weights",
        uri=relative_uri,
        sha256=checksum,
        size_bytes=size,
    )
    manifest = ModelManifest(
        model_version_id=uuid5(_NAMESPACE, f"{task}:{semantic_version}"),
        model_id=uuid5(_NAMESPACE, task),
        semantic_version=semantic_version,
        model_version_label=weights_path.stem,
        task=task,  # type: ignore[arg-type]
        runtime="ultralytics",
        input_width=imgsz,
        input_height=imgsz,
        class_names=class_names,
        artifacts=[artifact],
        datasets=[],
        split_strategy="by_capture_session",
        source_revision="av-train",
        training_config_revision=semantic_version,
        metrics=[],
        limitations=["Trained on developer hardware for static MVP; not production-accurate."],
        approved_by=None,
        approved_at=None,
        supersedes_model_version_id=None,
        created_at=datetime.now(UTC),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        _reject_existing_manifest_overwrite(output_path, checksum, semantic_version)
    output_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest
