"""Tests for the dependency-free host system metrics (design 15.3.1)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import assemblyvision_edge.system as system
import pytest


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


def test_read_net_counters_sums_non_loopback_interfaces(tmp_path: Path) -> None:
    netdev = tmp_path / "net_dev"
    netdev.write_text(
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        "    lo: 1000 10 0 0 0 0 0 0      1000 10 0 0 0 0 0 0\n"
        "  eth0: 4000 4 0 0 0 0 0 0      8000 8 0 0 0 0 0 0\n"
        "  wlan0: 6000 6 0 0 0 0 0 0      2000 2 0 0 0 0 0 0\n"
    )
    counters = system._read_net_counters(str(netdev))
    assert counters is not None
    rx, tx = counters
    assert rx == 10000
    assert tx == 10000


def test_network_rates_differencing(monkeypatch: pytest.MonkeyPatch) -> None:
    counters = iter([(1000, 2000), (7000, 6000), (15000, 9000)])
    monkeypatch.setattr(system, "_read_net_counters", lambda: next(counters))
    monkeypatch.setattr(system, "_net_sample", None)
    first = system.network_rates(now=0.0)
    assert first.rx_bps is None and first.tx_bps is None
    second = system.network_rates(now=2.0)
    assert second.rx_bps == pytest.approx(3000.0)
    assert second.tx_bps == pytest.approx(2000.0)
    third = system.network_rates(now=5.0)
    assert third.rx_bps == pytest.approx(8000.0 / 3.0)
    assert third.tx_bps == pytest.approx(3000.0 / 3.0)


def test_parse_gpu_line() -> None:
    metrics = system._parse_gpu_line(" 42, 55.5, 250 ")
    assert metrics.utilization_percent == pytest.approx(42.0)
    assert metrics.power_watts == pytest.approx(55.5)
    assert metrics.power_max_watts == pytest.approx(250.0)
    assert system._parse_gpu_line("garbage").utilization_percent is None


def test_gpu_metrics_fails_closed_when_smi_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(system, "_gpu_cache", None)
    metrics = system.gpu_metrics()
    assert metrics.utilization_percent is None
    assert metrics.power_watts is None
    assert metrics.power_max_watts is None


def test_gpu_metrics_fails_closed_when_smi_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise OSError("spawn failed")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(system, "_gpu_cache", None)
    metrics = system.gpu_metrics()
    assert metrics.utilization_percent is None
    assert metrics.power_watts is None
    assert metrics.power_max_watts is None
