"""Model artifact writer: weights checksum and manifest JSON."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from assemblyvision_domain.models import Artifact, ModelManifest

_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    manifest stays portable.
    """
    checksum = _sha256(weights_path)
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
    output_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest
