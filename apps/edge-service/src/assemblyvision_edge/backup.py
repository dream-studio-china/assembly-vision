"""Edge backup and restore (design 20.10, E5c).

``backup_edge`` takes a consistent point-in-time snapshot of the SQLite store
(SQLite online backup API), derives the pending-evidence inventory from that
snapshot (so the inventory and the restored store are the same point in time),
copies the governed configuration/rule/manifest files, and includes pending
evidence (media whose upload task has not succeeded) with SHA-256 checksums
into a single ``.tar.gz`` bundle.

``restore_edge`` verifies the bundle checksums before applying anything,
preflights every media target so a conflicting file fails with the active
store unchanged, restores pending media and their inspection records, swaps
the SQLite store last (keeping a ``.pre-restore`` copy), optionally restores
governed files into an explicit destination, and reconciles the store against
the root so pending upload tasks survive restore (E5 invariants 4-6).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from assemblyvision_domain.errors import ConfigError

from assemblyvision_edge.config import load_pipeline_config
from assemblyvision_edge.persistence.reconcile import reconcile_output_root
from assemblyvision_edge.persistence.repository import EdgeRepository, RepositoryError

log = logging.getLogger("assemblyvision.backup")

_MANIFEST_NAME = "manifest.json"
_DB_NAME = "edge.sqlite3"
_MEDIA_ROOT = "media"
_GOVERNED_ROOT = "governed"

# Upload task statuses that still require local evidence (design 20.11.2:
# pending uploads are never deleted; permanent failures keep their evidence).
_PENDING_MEDIA_SQL = """
    SELECT m.relative_path, m.checksum_sha256, m.size_bytes
    FROM media m
    JOIN upload_tasks t
      ON t.kind = 'MEDIA' AND t.object_id = m.media_id
    WHERE m.lifecycle != 'PURGED'
      AND t.status != 'SUCCEEDED'
"""


@dataclass(frozen=True)
class BackupReport:
    """Summary of one backup bundle."""

    bundle_path: Path
    governed_files: int
    pending_media: int
    bundle_sha256: str


@dataclass(frozen=True)
class RestoreReport:
    """Summary of one restore operation."""

    backup_path: Path
    restored_db: bool
    restored_media: int
    reconciled: int
    restored_governed: int = 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pending_media(db_path: Path) -> list[tuple[str, str, int]]:
    """Return pending (relative_path, checksum, size) rows from the store."""
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise ConfigError(f"cannot open edge database for backup: {db_path}: {exc}") from exc
    try:
        rows = connection.execute(_PENDING_MEDIA_SQL).fetchall()
        return [(str(row[0]), str(row[1]), int(row[2])) for row in rows]
    except sqlite3.Error as exc:
        raise ConfigError(f"cannot query pending media from {db_path}: {exc}") from exc
    finally:
        connection.close()


def _governed_files(config_path: Path | None, rule_path: Path | None) -> list[Path]:
    """Return the governed configuration, rule, and manifest files to back up.

    Missing manifests referenced by the pipeline configuration fail the backup
    closed because the decision-critical configuration cannot be reproduced.
    """
    files: list[Path] = []
    for path in (config_path, rule_path):
        if path is not None:
            if not path.is_file():
                raise ConfigError(f"governed file to back up is missing: {path}")
            files.append(path)
    if config_path is not None and config_path.is_file():
        pipeline = load_pipeline_config(config_path)
        for manifest in (pipeline.product_manifest, pipeline.component_manifest):
            if not manifest.is_file():
                raise ConfigError(f"model manifest to back up is missing: {manifest}")
            files.append(manifest)
    return files


def backup_edge(
    *,
    output_root: Path,
    db_path: Path,
    dest: Path,
    config_path: Path | None = None,
    rule_path: Path | None = None,
) -> BackupReport:
    """Create a consistent, checksummed backup bundle at ``dest``."""
    if not output_root.is_dir():
        raise ConfigError(f"output root does not exist: {output_root}")
    if not db_path.is_file():
        raise ConfigError(f"edge database does not exist: {db_path}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    governed = _governed_files(config_path, rule_path)

    with tempfile.TemporaryDirectory(prefix="av-backup-") as tmp:
        staging = Path(tmp)
        media_dir = staging / _MEDIA_ROOT
        media_dir.mkdir()
        governed_dir = staging / _GOVERNED_ROOT
        governed_dir.mkdir()

        # 1. Consistent online snapshot of the SQLite store.
        db_snapshot = staging / _DB_NAME
        _snapshot_db(db_path, db_snapshot)
        db_checksum = _sha256_file(db_snapshot)

        # 2. Derive the pending-media inventory from the snapshot, not the
        #    live database: records committed after the snapshot but before the
        #    inventory would otherwise be referenced by the restored store with
        #    no evidence in the bundle (E5 invariant 4).
        pending = _pending_media(db_snapshot)

        # 3. Governed configuration, rule, and manifests.
        manifest_entries: list[dict[str, str | int]] = []
        for index, source in enumerate(governed):
            target = governed_dir / f"{index:02d}-{source.name}"
            shutil.copy2(source, target)
            manifest_entries.append(
                {
                    "kind": "governed",
                    "source": str(source),
                    "bundle_path": str(target.relative_to(staging)),
                    "sha256": _sha256_file(target),
                    "size_bytes": target.stat().st_size,
                }
            )

        # 4. Pending evidence (media not yet uploaded) with checksums.
        pending_copied = 0
        inspection_records_copied: set[Path] = set()
        for relative_path, checksum, size in pending:
            source = output_root / relative_path
            # A missing or mismatched pending file is a hard failure: the
            # evidence cannot be reproduced and the backup would be a lie.
            if not source.is_file():
                raise ConfigError(f"pending media missing during backup: {source}")
            if size != source.stat().st_size or checksum != _sha256_file(source):
                raise ConfigError(f"pending media changed during backup: {source}")
            target = media_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            manifest_entries.append(
                {
                    "kind": "media",
                    "source": str(source.relative_to(output_root)),
                    "bundle_path": str(target.relative_to(staging)),
                    "sha256": checksum,
                    "size_bytes": size,
                }
            )
            inspection_record = Path(relative_path).parent / "inspection.json"
            if inspection_record not in inspection_records_copied:
                record_source = output_root / inspection_record
                if not record_source.is_file():
                    raise ConfigError(
                        f"pending media inspection record missing during backup: {record_source}"
                    )
                record_target = media_dir / inspection_record
                shutil.copy2(record_source, record_target)
                manifest_entries.append(
                    {
                        "kind": "inspection_record",
                        "source": str(inspection_record),
                        "bundle_path": str(record_target.relative_to(staging)),
                        "sha256": _sha256_file(record_target),
                        "size_bytes": record_target.stat().st_size,
                    }
                )
                inspection_records_copied.add(inspection_record)
            pending_copied += 1

        manifest = {
            "format_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "database": {"bundle_path": _DB_NAME, "sha256": db_checksum},
            "entries": manifest_entries,
        }
        (staging / _MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )

        # 5. Bundle tar.gz and its own checksum.
        with tarfile.open(dest, "w:gz") as archive:
            archive.add(staging / _MANIFEST_NAME, arcname=_MANIFEST_NAME)
            archive.add(staging / _DB_NAME, arcname=_DB_NAME)
            if pending_copied:
                archive.add(media_dir, arcname=_MEDIA_ROOT)
            if governed:
                archive.add(governed_dir, arcname=_GOVERNED_ROOT)
        return BackupReport(
            bundle_path=dest,
            governed_files=len(governed),
            pending_media=pending_copied,
            bundle_sha256=_sha256_file(dest),
        )


def _snapshot_db(source: Path, target: Path) -> None:
    """Copy a live SQLite database consistently via the online backup API."""
    try:
        src = sqlite3.connect(str(source), timeout=5)
    except sqlite3.Error as exc:
        raise ConfigError(f"cannot open edge database {source}: {exc}") from exc
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        except sqlite3.Error as exc:
            raise ConfigError(f"database backup failed for {source}: {exc}") from exc
        finally:
            dst.close()
    finally:
        src.close()


@dataclass(frozen=True)
class _BundleEntry:
    """One file inside a backup bundle, with its checksum."""

    kind: str
    source: str
    bundle_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class _BundleManifest:
    """Typed backup bundle manifest (E5c)."""

    database_sha256: str
    entries: list[_BundleEntry]


def _load_bundle_manifest(bundle: Path) -> _BundleManifest:
    """Return the validated bundle manifest, or raise for a corrupt bundle."""
    try:
        with tarfile.open(bundle, "r:gz") as archive:
            member = archive.getmember(_MANIFEST_NAME)
            raw = archive.extractfile(member)
            if raw is None:
                raise ConfigError(f"backup bundle {bundle} has an empty manifest")
            document = json.loads(raw.read().decode("utf-8"))
    except (OSError, tarfile.TarError, json.JSONDecodeError, KeyError) as exc:
        raise ConfigError(f"backup bundle {bundle} is invalid: {exc}") from exc
    if document.get("format_version") != 1:
        raise ConfigError("unsupported backup bundle format_version")
    database = document.get("database")
    entries = document.get("entries")
    if not isinstance(database, dict) or not isinstance(entries, list):
        raise ConfigError(f"backup bundle {bundle} has a malformed manifest")
    try:
        parsed_entries = [
            _BundleEntry(
                kind=str(entry["kind"]),
                source=str(entry["source"]),
                bundle_path=str(entry["bundle_path"]),
                sha256=str(entry["sha256"]),
                size_bytes=int(entry["size_bytes"]),
            )
            for entry in entries
            if isinstance(entry, dict)
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"backup bundle {bundle} has a malformed manifest: {exc}") from exc
    return _BundleManifest(database_sha256=str(database.get("sha256")), entries=parsed_entries)


def restore_edge(
    *,
    backup: Path,
    output_root: Path,
    db_path: Path,
    governed_dest: Path | None = None,
) -> RestoreReport:
    """Restore a verified backup bundle without destroying local evidence.

    Governed configuration/rule/manifest files are restored only when
    ``governed_dest`` names the approved release directory; the restored store
    is reconciled against the output root so pending upload tasks survive.
    """
    if not backup.is_file():
        raise ConfigError(f"backup bundle does not exist: {backup}")
    manifest = _load_bundle_manifest(backup)
    output_root.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    restored_media = 0
    restored_governed = 0
    with tempfile.TemporaryDirectory(prefix="av-restore-") as tmp:
        staging = Path(tmp)
        with tarfile.open(backup, "r:gz") as archive:
            # Verify every entry checksum before applying anything (E5
            # invariant 6): extract to staging, then verify.
            archive.extractall(staging, filter="data")
        snapshot = staging / _DB_NAME
        if not snapshot.is_file():
            raise ConfigError("backup bundle is missing the database snapshot")
        if _sha256_file(snapshot) != manifest.database_sha256:
            raise ConfigError("backup bundle database checksum mismatch; refusing to restore")
        for entry in manifest.entries:
            bundle_path = staging / entry.bundle_path
            if not bundle_path.is_file():
                raise ConfigError(f"backup bundle entry missing: {entry.source}")
            if _sha256_file(bundle_path) != entry.sha256:
                raise ConfigError(f"backup bundle entry checksum mismatch: {entry.source}")

        # Preflight every media/record target before touching the store: a
        # conflicting existing file must fail the restore with the active
        # database unchanged (E5 invariant 6).
        media_root = staging / _MEDIA_ROOT
        plan: list[tuple[str, Path, Path]] = []
        for entry in manifest.entries:
            if entry.kind not in {"media", "inspection_record"}:
                continue
            target = output_root / Path(entry.source)
            if target.exists():
                if target.is_file() and _sha256_file(target) == entry.sha256:
                    continue  # already restored; keep in place
                raise ConfigError(f"restore would overwrite conflicting file: {target}")
            plan.append((entry.kind, media_root / entry.source, target))

        # Restore pending media and their inspection records first so an apply
        # failure leaves the active database unchanged. The records keep
        # restored directories valid when startup reconciliation checks for
        # orphan evidence bundles.
        for kind, bundle_source, target in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundle_source, target)
            if kind == "media":
                restored_media += 1

        # Restore governed files into the approved release directory; names
        # must not collide and existing files are never overwritten.
        governed_entries = [entry for entry in manifest.entries if entry.kind == "governed"]
        if governed_dest is not None:
            used: dict[str, str] = {}
            for entry in governed_entries:
                name = Path(entry.source).name
                if name in used:
                    raise ConfigError(
                        "governed files share a basename; refusing to restore: "
                        f"{used[name]} and {entry.source}"
                    )
                used[name] = entry.source
            for entry in governed_entries:
                name = Path(entry.source).name
                target = governed_dest / name
                if target.exists():
                    if _sha256_file(target) == entry.sha256:
                        continue  # already restored; keep in place
                    raise ConfigError(
                        f"restore would overwrite conflicting governed file: {target}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(staging / entry.bundle_path, target)
                restored_governed += 1
        elif governed_entries:
            log.warning(
                "backup bundle contains %d governed file(s) but no governed "
                "destination was given; they were not restored",
                len(governed_entries),
            )

        # Apply the store swap last, keeping a copy of the current database.
        if db_path.exists():
            shutil.copy2(db_path, db_path.with_name(f"{db_path.name}.pre-restore"))
        shutil.copy2(snapshot, db_path)

    # Reconcile the restored store against the output root so inspection
    # records and pending upload tasks are rebuilt consistently.
    try:
        repository = EdgeRepository.open(str(db_path))
        try:
            reconciled = reconcile_output_root(repository, output_root)
        finally:
            repository.close()
    except (OSError, RuntimeError, RepositoryError, sqlite3.Error) as exc:
        raise ConfigError(f"restore reconciliation failed: {exc}") from exc

    return RestoreReport(
        backup_path=backup,
        restored_db=True,
        restored_media=restored_media,
        restored_governed=restored_governed,
        reconciled=reconciled,
    )
