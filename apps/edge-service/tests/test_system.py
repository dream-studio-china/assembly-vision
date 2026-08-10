"""Tests for the dependency-free host system metrics (design 15.3.1)."""

from __future__ import annotations

from pathlib import Path

import assemblyvision_edge.system as system


def test_system_metrics_shape() -> None:
    metrics = system.system_metrics()
    assert metrics.cpu_count is None or metrics.cpu_count >= 1
    assert metrics.load_1m is None or metrics.load_1m >= 0.0
    assert metrics.memory_total_bytes is None or metrics.memory_total_bytes > 0
    assert metrics.memory_available_bytes is None or metrics.memory_available_bytes >= 0


def test_memory_bytes_parses_proc_meminfo(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       16384000 kB\n"
        "MemFree:        2048000 kB\n"
        "MemAvailable:   4096000 kB\n"
        "SwapTotal:      0 kB\n"
    )
    total, available = system._memory_bytes(str(meminfo))
    assert total == 16384000 * 1024
    assert available == 4096000 * 1024


def test_memory_bytes_falls_back_when_proc_meminfo_missing(tmp_path: Path) -> None:
    total, available = system._memory_bytes(str(tmp_path / "missing"))
    assert available is None
    assert total is None or total > 0
