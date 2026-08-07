"""Startup reconciliation: import existing CLI inspection output.

The static MVP CLI writes one ``inspection.json`` per inspection under the
output root. On startup the service imports every valid record idempotently so
the dashboard can display real results produced before the API existed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from assemblyvision_domain.models import InspectionRecord

from assemblyvision_edge.persistence.repository import EdgeRepository

log = logging.getLogger("assemblyvision.reconcile")


def reconcile_output_root(repository: EdgeRepository, output_root: Path) -> int:
    """Import all inspection.json files found in the output root.

    Returns the number of newly imported inspections. Already-published
    inspection IDs are skipped; corrupt files are logged and skipped without
    aborting the scan.
    """
    if not output_root.is_dir():
        return 0
    imported = 0
    for path in sorted(output_root.glob("*/inspection.json")):
        if path.parent.name.startswith(".staging"):
            continue
        if repository.get_inspection(path.parent.name) is not None:
            continue
        try:
            record = InspectionRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("skipping invalid inspection record %s: %s", path, exc)
            continue
        repository.upsert_inspection(record)
        imported += 1
        log.info("imported inspection %s from %s", record.inspection_id, path)
    return imported
