"""Dependency-free host system metrics for the device health view (15.3.1).

Load, CPU count, and memory are read with the standard library only (the
edge runs Linux in production and macOS for development; no psutil
dependency). Metrics are best-effort observability: an unavailable value is
reported as None so the dashboard renders it as unavailable instead of
fabricating a number.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemMetrics:
    cpu_count: int | None = None
    load_1m: float | None = None
    memory_total_bytes: int | None = None
    memory_available_bytes: int | None = None


def _load_1m() -> float | None:
    try:
        load = os.getloadavg()
    except (AttributeError, OSError):
        return None
    return float(load[0])


def _memory_bytes(path: str = "/proc/meminfo") -> tuple[int | None, int | None]:
    """Return (total, available) bytes, falling back to sysconf totals.

    ``MemAvailable`` exists only on Linux; on other platforms the available
    value stays None and the dashboard shows the total only.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            meminfo = handle.read()
    except OSError:
        return _memory_sysconf(), None
    fields: dict[str, int] = {}
    for line in meminfo.splitlines():
        key, rest = line.split(":", 1)
        fields[key] = int(rest.strip().split()[0]) * 1024  # kB -> bytes
    return fields.get("MemTotal"), fields.get("MemAvailable")


def _memory_sysconf() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None
    return int(pages) * int(page_size)


def system_metrics() -> SystemMetrics:
    """Sample host load, CPU count, and memory without third-party packages."""
    total, available = _memory_bytes()
    return SystemMetrics(
        cpu_count=os.cpu_count(),
        load_1m=_load_1m(),
        memory_total_bytes=total,
        memory_available_bytes=available,
    )
