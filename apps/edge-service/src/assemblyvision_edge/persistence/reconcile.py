"""Startup reconciliation: import existing CLI inspection output.

The static MVP CLI writes one ``inspection.json`` per inspection under the
output root. On startup the service imports every valid record idempotently so
the dashboard can display real results produced before the API existed.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from assemblyvision_domain.models import InspectionRecord

from assemblyvision_edge.persistence.repository import (
    EdgeRepository,
    MediaIdentity,
    RepositoryError,
)

log = logging.getLogger("assemblyvision.reconcile")


def media_path_is_safe(output_root: Path, inspection_id: str, relative_path: str) -> bool:
    """Return False for empty, absolute, or traversal-escaping media paths.

    The resolved path must stay inside the record's final inspection directory,
    not merely inside the shared output root. This prevents a crafted bundle
    from exposing the SQLite index, configuration, or another inspection's
    media through the media endpoint.
    """
    if not relative_path:
        return False
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        return False
    root = output_root.resolve()
    inspection_dir = Path(inspection_id)
    if path.parent == Path(".") or path.parts[0] != inspection_dir.name:
        return False
    try:
        bundle_root = (root / inspection_dir).resolve()
        return bundle_root.is_relative_to(root) and (root / path).resolve().is_relative_to(
            bundle_root
        )
    except (OSError, ValueError):
        # OSError: resolution failed (for example a broken symlink).
        # ValueError: the path contains an embedded NUL byte, which the host
        # filesystem cannot address. Both mean the media path cannot be
        # served; treat it as unsafe so a malformed bundle is skipped whole.
        return False


def quarantine_stale_staging(output_root: Path) -> int:
    """Move crash-left ``.staging-*`` directories into ``quarantine/``.

    Process termination can bypass the writer's in-process cleanup, leaving
    orphan staging bundles that consume disk and are not valid inspection
    directories. They are moved aside and never imported (P2).
    """
    if not output_root.is_dir():
        return 0
    quarantine_dir = output_root / "quarantine"
    quarantined = 0
    for staging in sorted(output_root.glob(".staging-*")):
        if not staging.is_dir():
            continue
        quarantine_dir.mkdir(exist_ok=True)
        try:
            staging.rename(quarantine_dir / staging.name)
        except OSError as exc:
            log.warning("cannot quarantine staging dir %s: %s", staging, exc)
            continue
        quarantined += 1
        log.warning("quarantined crash-left staging bundle %s", staging.name)
    return quarantined


def quarantine_bundle(output_root: Path, directory: Path, reason: str) -> bool:
    """Move a malformed/ambiguous final bundle into ``quarantine/`` (E2d).

    Ambiguous evidence is preserved in the quarantine directory, never
    re-imported, overwritten, or deleted (E2 task invariant 8/9). Returns True
    when the bundle was moved.
    """
    if not directory.is_dir():
        return False
    quarantine_dir = output_root / "quarantine"
    quarantine_dir.mkdir(exist_ok=True)
    try:
        directory.rename(quarantine_dir / directory.name)
    except OSError as exc:
        log.warning("cannot quarantine %s bundle %s: %s", reason, directory.name, exc)
        return False
    log.warning("quarantined %s bundle %s", reason, directory.name)
    return True


@dataclass(frozen=True)
class IntegrityScanReport:
    """Result of the startup media/filesystem integrity scan (E2d).

    ``checked`` is the number of projected media artifacts examined; ``faults``
    counts artifacts marked ``FAULT``. ``checksum_checked``/``skipped`` record
    how many artifacts were actually checksum-verified under the configured
    sampling policy and how many were size-checked only (PR-020 F09).
    """

    checked: int
    faults: int
    fault_codes: dict[str, int]
    checksum_checked: int = 0
    skipped: int = 0
    skipped_reason: str | None = None


def _verify_media(output_root: Path, identity: MediaIdentity, verify_checksums: bool) -> str | None:
    """Return a fault code when a projected media artifact is inconsistent."""
    if not media_path_is_safe(output_root, str(identity.inspection_id), identity.relative_path):
        return "MEDIA_PATH_UNSAFE"
    path = output_root / identity.relative_path
    if not path.is_file():
        return "MEDIA_EVIDENCE_MISSING"
    if path.stat().st_size != identity.size_bytes:
        return "MEDIA_SIZE_MISMATCH"
    if verify_checksums:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != identity.checksum_sha256:
            return "MEDIA_CHECKSUM_MISMATCH"
    return None


def scan_storage_integrity(
    repository: EdgeRepository,
    output_root: Path,
    *,
    verify_checksums: bool = False,
    sample_limit: int | None = None,
    sample_max_bytes: int | None = None,
) -> IntegrityScanReport:
    """Verify projected media against the filesystem and mark faults (E2d).

    Runs at startup before any worker: missing files, size mismatches, unsafe
    paths, and (when enabled) checksum mismatches durably mark the artifact
    ``integrity_status='FAULT'`` so it is protected from retention deletion
    until an operator reconciles it (design 12.8).

    Checksum verification is bounded deterministically by ``sample_limit``
    (number of files) and ``sample_max_bytes`` (total bytes read) using stable
    ordering; artifacts outside the budget are size-checked only and reported
    as skipped (PR-020 F09).
    """
    faults = 0
    codes: dict[str, int] = {}
    checksummed = 0
    skipped = 0
    budget_bytes = sample_max_bytes
    identities = repository.list_media_for_integrity()
    for identity in identities:
        code = _verify_media(output_root, identity, verify_checksums=False)
        if code is not None:
            repository.mark_media_integrity_fault_direct(str(identity.media_id), code)
            faults += 1
            codes[code] = codes.get(code, 0) + 1
            continue
        if not verify_checksums:
            continue
        if sample_limit is not None and checksummed >= sample_limit:
            skipped += 1
            continue
        if budget_bytes is not None and budget_bytes < identity.size_bytes:
            skipped += 1
            continue
        if budget_bytes is not None:
            budget_bytes -= identity.size_bytes
        checksummed += 1
        checksum_code = _verify_media(output_root, identity, verify_checksums=True)
        if checksum_code is not None:
            repository.mark_media_integrity_fault_direct(str(identity.media_id), checksum_code)
            faults += 1
            codes[checksum_code] = codes.get(checksum_code, 0) + 1
    skipped_reason = None
    if skipped:
        skipped_reason = "sample_limit" if sample_limit is not None else "sample_max_bytes"
    return IntegrityScanReport(
        checked=len(identities),
        faults=faults,
        fault_codes=codes,
        checksum_checked=checksummed,
        skipped=skipped,
        skipped_reason=skipped_reason,
    )


def reconcile_output_root(repository: EdgeRepository, output_root: Path) -> int:
    """Import all inspection.json files found in the output root.

    Returns the number of newly imported inspections. Corrupt, unsafe, or
    conflicting bundles are moved to ``quarantine/`` (durably preserved,
    never silently re-imported or deleted, E2d) without aborting the scan.
    Crash-left ``.staging-*`` bundles are quarantined first.

    The atomic persist-and-enqueue operation is applied to every valid bundle,
    not just newly inserted ones, so a stranded ``LOCAL_ONLY`` record whose
    outbox tasks were lost in a crash is repaired instead of being skipped
    (PR-017 F2).
    """
    if not output_root.is_dir():
        return 0
    quarantine_stale_staging(output_root)
    imported = 0
    for path in sorted(output_root.glob("*/inspection.json")):
        if path.parent.name.startswith((".staging", "quarantine")):
            continue
        try:
            record = InspectionRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("skipping invalid inspection record %s: %s", path, exc)
            quarantine_bundle(output_root, path.parent, "invalid")
            continue
        unsafe = [
            item.relative_path
            for item in record.media
            if not media_path_is_safe(output_root, str(record.inspection_id), item.relative_path)
        ]
        if path.parent.name != str(record.inspection_id) or unsafe:
            log.warning(
                "skipping inspection %s with unsafe media paths: %s", record.inspection_id, unsafe
            )
            quarantine_bundle(output_root, path.parent, "unsafe-media")
            continue
        try:
            status = repository.persist_inspection_and_enqueue_uploads(record)
        except RepositoryError as exc:
            log.warning("skipping conflicting inspection %s: %s", record.inspection_id, exc)
            quarantine_bundle(output_root, path.parent, "content-conflict")
            continue
        if status == "inserted":
            imported += 1
            log.info("imported inspection %s from %s", record.inspection_id, path)
    return imported
