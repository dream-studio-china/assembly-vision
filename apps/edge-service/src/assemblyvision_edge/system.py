"""Dependency-free host system metrics for the device health view (15.3.1).

Load, CPU count, and memory are read with the standard library only (the
edge runs Linux in production and macOS for development; no psutil
dependency). Network rates are derived by differencing the cumulative
``/proc/net/dev`` counters, and GPU metrics come from ``nvidia-smi`` when an
NVIDIA GPU is present. Metrics are best-effort observability: an unavailable
value is reported as None so the dashboard renders it as unavailable instead
of fabricating a number.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemMetrics:
    cpu_count: int | None = None
    load_1m: float | None = None
    memory_total_bytes: int | None = None
    memory_available_bytes: int | None = None


@dataclass(frozen=True)
class NetworkRates:
    rx_bps: float | None = None
    tx_bps: float | None = None


@dataclass(frozen=True)
class GpuMetrics:
    utilization_percent: float | None = None
    power_watts: float | None = None
    power_max_watts: float | None = None


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


def _read_net_counters(path: str = "/proc/net/dev") -> tuple[int, int] | None:
    """Return summed (rx_bytes, tx_bytes) over non-loopback interfaces."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    rx = 0
    tx = 0
    for line in lines:
        if ":" not in line:
            continue
        iface, rest = line.split(":", 1)
        if iface.strip() == "lo":
            continue
        fields = rest.split()
        if len(fields) >= 9:
            rx += int(fields[0])
            tx += int(fields[8])
    return rx, tx


# Last (sampled_at, (rx, tx)) used to derive rates between device-status polls.
_net_sample: tuple[float, tuple[int, int]] | None = None


def network_rates(*, now: float | None = None) -> NetworkRates:
    """Bytes-per-second rates derived by differencing cumulative counters.

    The first poll has no previous sample and reports None; every later poll
    reports the average rate since the previous poll. ``now`` is injectable
    for deterministic tests and defaults to the monotonic clock.
    """
    global _net_sample
    counters = _read_net_counters()
    if counters is None:
        return NetworkRates()
    now = now if now is not None else time.monotonic()
    previous = _net_sample
    _net_sample = (now, counters)
    if previous is None or now <= previous[0]:
        return NetworkRates()
    elapsed = now - previous[0]
    prev_rx, prev_tx = previous[1]
    rx_bps = max(0.0, (counters[0] - prev_rx) / elapsed)
    tx_bps = max(0.0, (counters[1] - prev_tx) / elapsed)
    return NetworkRates(rx_bps=rx_bps, tx_bps=tx_bps)


def _parse_gpu_line(line: str) -> GpuMetrics:
    """Parse one nvidia-smi csv row: utilization.gpu,power.draw,power.limit."""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 3:
        return GpuMetrics()

    def parse(value: str) -> float | None:
        try:
            return float(value)
        except ValueError:
            return None

    return GpuMetrics(
        utilization_percent=parse(parts[0]),
        power_watts=parse(parts[1]),
        power_max_watts=parse(parts[2]),
    )


# nvidia-smi is invoked at most every few seconds per process.
_gpu_cache: tuple[float, GpuMetrics] | None = None
_GPU_CACHE_TTL_SECONDS = 5.0


def gpu_metrics() -> GpuMetrics:
    """Sample NVIDIA GPU utilization and power via nvidia-smi, if present.

    A missing binary, non-NVIDIA host, or query failure yields an empty
    GpuMetrics (all None); the dashboard then shows the gauges as
    unavailable rather than fabricating values.
    """
    global _gpu_cache
    now = time.monotonic()
    if _gpu_cache is not None and now - _gpu_cache[0] < _GPU_CACHE_TTL_SECONDS:
        return _gpu_cache[1]
    smi = shutil.which("nvidia-smi")
    if smi is None:
        _gpu_cache = (now, GpuMetrics())
        return _gpu_cache[1]
    try:
        # The binary comes from the system PATH and the arguments are fixed
        # query constants, so there is no untrusted input to the call.
        result = subprocess.run(  # noqa: S603
            [
                smi,
                "--query-gpu=utilization.gpu,power.draw,power.limit",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _gpu_cache = (now, GpuMetrics())
        return _gpu_cache[1]
    metrics = GpuMetrics()
    if result.returncode == 0 and result.stdout.strip():
        metrics = _parse_gpu_line(result.stdout.strip().splitlines()[0])
    _gpu_cache = (now, metrics)
    return metrics
