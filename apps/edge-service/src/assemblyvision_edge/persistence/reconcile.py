"""Startup reconciliation: import existing CLI inspection output.

The static MVP CLI writes one ``inspection.json`` per inspection under the
output root. On startup the service imports every valid record idempotently so
the dashboard can display real results produced before the API existed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from assemblyvision_domain.models import InspectionRecord

from assemblyvision_edge.persistence.repository import EdgeRepository, RepositoryError

log = logging.getLogger("assemblyvision.reconcile")


def media_path_is_safe(output_root: Path, relative_path: str) -> bool:
    """Return False for empty, absolute, or traversal-escaping media paths.

    The resolved path must stay inside the media root so that reconciliation
    never imports a record whose content could later be served outside it.
    """
    if not relative_path:
        return False
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        return False
    root = output_root.resolve()
    try:
        return (root / path).resolve().is_relative_to(root)
    except OSError:
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


def reconcile_output_root(repository: EdgeRepository, output_root: Path) -> int:
    """Import all inspection.json files found in the output root.

    Returns the number of newly imported inspections. Corrupt files are logged
    and skipped without aborting the scan. Records whose media paths escape the
    output root, or whose immutable content conflicts with an existing
    inspection ID, are skipped whole so no partially validated record is
    imported. Crash-left ``.staging-*`` bundles are quarantined first.
    """
    if not output_root.is_dir():
        return 0
    quarantine_stale_staging(output_root)
    imported = 0
    for path in sorted(output_root.glob("*/inspection.json")):
        if path.parent.name.startswith(".staging"):
            continue
        try:
            record = InspectionRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("skipping invalid inspection record %s: %s", path, exc)
            continue
        unsafe = [
            item.relative_path
            for item in record.media
            if not media_path_is_safe(output_root, item.relative_path)
        ]
        if unsafe:
            log.warning(
                "skipping inspection %s with unsafe media paths: %s", record.inspection_id, unsafe
            )
            continue
        try:
            status = repository.upsert_inspection(record)
        except RepositoryError as exc:
            log.warning("skipping conflicting inspection %s: %s", record.inspection_id, exc)
            continue
        if status == "inserted":
            imported += 1
            log.info("imported inspection %s from %s", record.inspection_id, path)
    return imported
