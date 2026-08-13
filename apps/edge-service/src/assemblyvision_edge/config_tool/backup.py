"""Configuration backup and rollback.

Every write through the config tool snapshots the current file first into
``<config-dir>/.assemblyvision-backups/`` so a mistaken edit can be rolled back.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_BACKUP_DIR_NAME = ".assemblyvision-backups"


@dataclass(frozen=True)
class BackupEntry:
    """One snapshot of a configuration file."""

    backup_path: Path
    original_name: str
    created_at: datetime


def backup_dir_for(config_path: Path) -> Path:
    """Return the backup directory for a configuration file."""
    return config_path.parent / _BACKUP_DIR_NAME


def create_backup(config_path: Path) -> Path:
    """Snapshot ``config_path``; returns the backup file path."""
    if not config_path.exists():
        raise FileNotFoundError(f"no file to back up: {config_path}")
    backup_dir = backup_dir_for(config_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"{config_path.name}.{stamp}.bak"
    shutil.copy2(config_path, backup_path)
    return backup_path


def list_backups(config_path: Path) -> list[BackupEntry]:
    """Return backups for ``config_path``, newest first."""
    backup_dir = backup_dir_for(config_path)
    if not backup_dir.exists():
        return []
    entries: list[BackupEntry] = []
    prefix = f"{config_path.name}."
    for candidate in sorted(backup_dir.iterdir(), reverse=True):
        if (
            candidate.is_file()
            and candidate.name.startswith(prefix)
            and candidate.name.endswith(".bak")
        ):
            stamp = candidate.name[len(prefix) : -len(".bak")]
            try:
                created_at = datetime.strptime(stamp, "%Y%m%d-%H%M%S-%f").replace(tzinfo=UTC)
            except ValueError:
                continue
            entries.append(BackupEntry(candidate, config_path.name, created_at))
    return entries


def restore_backup(config_path: Path, backup_path: Path) -> None:
    """Restore ``backup_path`` over ``config_path`` (idempotent)."""
    if not backup_path.exists():
        raise FileNotFoundError(f"backup does not exist: {backup_path}")
    shutil.copy2(backup_path, config_path)
