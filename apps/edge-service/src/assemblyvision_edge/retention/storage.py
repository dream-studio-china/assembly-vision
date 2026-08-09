"""Disk-pressure observation for the edge runtime (design 12.7, E2c).

The runtime observes free bytes and free inodes on the persistent output
volume and derives a stable pressure mode from the configured thresholds. At
or below ``stop`` the runtime must not accept new products when mandatory
persistence cannot be guaranteed (E2 task invariant 7/8).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from assemblyvision_edge.api.settings import StorageSettings

PressureMode = Literal["NORMAL", "WARNING", "CRITICAL", "STOP"]


@dataclass(frozen=True)
class StorageState:
    """One storage observation with the derived pressure mode (E2c)."""

    mode: PressureMode
    free_bytes: int
    total_bytes: int
    free_percent: float
    free_inodes: int
    total_inodes: int
    inode_free_percent: float
    warning_free_percent: float
    critical_free_percent: float
    stop_free_percent: float
    observed_at: str


class StorageObservationError(OSError):
    """Raised when the persistent volume cannot be measured (E2 task 8)."""


def observe_storage(path: Path, settings: StorageSettings | None) -> StorageState:
    """Measure the output volume and derive the pressure mode.

    Raises :class:`StorageObservationError` when the volume cannot be read so
    the runtime enters a storage fault instead of assuming health.
    """
    try:
        usage = shutil.disk_usage(path)
        stat = os.statvfs(path)
    except OSError as exc:
        raise StorageObservationError(f"cannot measure storage volume {path}: {exc}") from exc
    free_bytes = int(usage.free)
    total_bytes = int(usage.total)
    free_percent = (free_bytes / total_bytes * 100.0) if total_bytes else 0.0
    total_inodes = int(stat.f_files)
    free_inodes = int(stat.f_ffree)
    inode_percent = (free_inodes / total_inodes * 100.0) if total_inodes else 0.0

    defaults = StorageSettings()
    warning = (
        settings.warning_free_percent if settings is not None else defaults.warning_free_percent
    )
    critical = (
        settings.critical_free_percent if settings is not None else defaults.critical_free_percent
    )
    stop = settings.stop_free_percent if settings is not None else defaults.stop_free_percent

    mode: PressureMode = "NORMAL"
    # "At or below" semantics (design 12.7, PR-020 F06): exactly the stop
    # reserve is STOP, exactly the critical reserve is CRITICAL, and exactly
    # the warning reserve is WARNING.
    if free_percent <= stop or inode_percent <= stop:
        mode = "STOP"
    elif free_percent <= critical or inode_percent <= critical:
        mode = "CRITICAL"
    elif free_percent <= warning or inode_percent <= warning:
        mode = "WARNING"
    return StorageState(
        mode=mode,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        free_percent=round(free_percent, 3),
        free_inodes=free_inodes,
        total_inodes=total_inodes,
        inode_free_percent=round(inode_percent, 3),
        warning_free_percent=warning,
        critical_free_percent=critical,
        stop_free_percent=stop,
        observed_at=datetime.now(UTC).isoformat(),
    )
