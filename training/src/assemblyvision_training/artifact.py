"""Model artifact writer: weights checksum and manifest JSON."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
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


def _canonical_manifest_payload(manifest: ModelManifest) -> str:
    """Canonical JSON of every decision-critical manifest field.

    ``created_at`` is excluded because it changes on every write and carries no
    release semantics; every other field (task, class order, input size,
    artifact uri/checksum, provenance) is part of the immutable identity
    (PR-003 P1: manifest content binding).
    """
    payload = manifest.model_dump(mode="json")
    payload.pop("created_at", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


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
    manifest stays portable. An existing manifest for the same semantic version
    is only accepted when its full decision-critical content matches exactly;
    otherwise publication is refused so versioned identities stay immutable.
    A matching manifest is returned without being rewritten (idempotent).
    """
    if not _SEMVER_RE.match(semantic_version):
        raise ConfigError(f"semantic_version {semantic_version!r} is not a valid X.Y.Z version")
    checksum = sha256_file(weights_path)
    size = weights_path.stat().st_size
    relative_uri = os.path.relpath(Path(weights_path).resolve(), output_path.parent.resolve())

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
        try:
            existing = ModelManifest.model_validate_json(output_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ConfigError(
                f"existing manifest {output_path} is invalid; refusing to overwrite: {exc}"
            ) from exc
        if _canonical_manifest_payload(existing) != _canonical_manifest_payload(manifest):
            raise ConfigError(
                f"refusing to overwrite existing manifest {output_path}: decision-critical "
                "content differs (class order, task, input size, artifact, or provenance); "
                "bump --semver or remove the file"
            )
        return existing
    output_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_run_metadata(
    *,
    task: str,
    semantic_version: str,
    dataset_dir: Path,
    weights_path: Path,
    epochs: int,
    imgsz: int,
    seed: int,
    model_size: str,
    device: str,
    no_augment: bool,
    output_path: Path,
) -> Path:
    """Record training-run reproducibility metadata next to the manifest.

    Design 19.8 requires each run to record seeds, dataset references,
    architecture, image size, epochs, augmentation, and framework versions.
    The sidecar is written beside the manifest (``<name>.run.json``) and is
    immutable per published version; a repeat run with identical bytes is
    idempotent.
    """
    dataset_manifest = dataset_dir / "data.yaml"
    dataset_sha = sha256_file(dataset_manifest) if dataset_manifest.is_file() else None
    try:
        ultralytics_version = version("ultralytics")
    except PackageNotFoundError:  # pragma: no cover - environment dependent
        ultralytics_version = "unknown"
    payload: dict[str, object] = {
        "task": task,
        "semantic_version": semantic_version,
        "dataset_dir": str(dataset_dir.resolve()),
        "dataset_data_yaml_sha256": dataset_sha,
        "epochs": epochs,
        "imgsz": imgsz,
        "seed": seed,
        "model_size": model_size,
        "augmentations_disabled": no_augment,
        "device": device,
        "weights_sha256": sha256_file(weights_path),
        "weights_size_bytes": weights_path.stat().st_size,
        "python_version": platform.python_version(),
        "ultralytics_version": ultralytics_version,
        "created_at": datetime.now(UTC).isoformat(),
    }
    # created_at changes on every run and carries no reproducibility meaning,
    # so it is excluded from the immutability comparison.
    stable_payload = {k: v for k, v in payload.items() if k != "created_at"}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(
                f"existing run metadata {output_path} is invalid; refusing to overwrite: {exc}"
            ) from exc
        if {k: v for k, v in existing.items() if k != "created_at"} != stable_payload:
            raise ConfigError(
                f"refusing to overwrite existing run metadata {output_path}: content differs; "
                "bump --semver or remove the file"
            )
        return output_path
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
