"""Focused contract tests for the unintegrated Modbus TCP FIFO trigger adapter."""

from __future__ import annotations

from collections import deque

import pytest
from assemblyvision_edge.trigger.modbus_tcp import (
    InconsistentPlcSnapshotError,
    ModbusTcpTriggerAdapter,
    ModbusTcpTriggerConfig,
    PlcEventSequenceError,
    PlcFifoEvent,
    PlcFifoOverflowError,
    PlcFifoSnapshot,
    PlcFifoSnapshotProfile,
    PlcTriggerEventType,
    StalePlcHeartbeatError,
    TriggerReadMode,
)


class FakeTransport:
    def __init__(self, snapshots: list[PlcFifoSnapshot]) -> None:
        self._snapshots = deque(snapshots)
        self.calls = 0

    def read_fifo_snapshot(self, profile: PlcFifoSnapshotProfile) -> PlcFifoSnapshot:
        self.calls += 1
        return self._snapshots.popleft()


def _snapshot(
    *events: PlcFifoEvent,
    sequence: int = 1,
    heartbeat: int = 1,
    overflow: bool = False,
    sequence_after: int | None = None,
) -> PlcFifoSnapshot:
    return PlcFifoSnapshot(
        sequence_before=sequence,
        events=events,
        heartbeat=heartbeat,
        overflow=overflow,
        sequence_after=sequence if sequence_after is None else sequence_after,
    )


def _event(sequence: int) -> PlcFifoEvent:
    return PlcFifoEvent(sequence, PlcTriggerEventType.ENTRY, f"product-{sequence}")


def _adapter(
    snapshots: list[PlcFifoSnapshot], *, clock: list[float] | None = None
) -> ModbusTcpTriggerAdapter:
    times = iter(clock or [0.0])
    return ModbusTcpTriggerAdapter(
        FakeTransport(snapshots),
        ModbusTcpTriggerConfig(enabled=True, heartbeat_timeout_s=2.0),
        clock=lambda: next(times, 0.0),
    )


def test_disabled_adapter_does_not_contact_transport() -> None:
    transport = FakeTransport([])
    adapter = ModbusTcpTriggerAdapter(transport)

    assert adapter.poll() == ()
    assert transport.calls == 0


def test_rejects_ordinary_coil_polling_profile() -> None:
    with pytest.raises(ValueError, match="coil polling"):
        PlcFifoSnapshotProfile(read_mode=TriggerReadMode.COIL_POLL)


def test_rejects_duplicate_and_gapped_event_sequences() -> None:
    duplicate = _adapter([_snapshot(_event(10)), _snapshot(_event(10), heartbeat=2)])
    assert duplicate.poll()[0].sequence == 10
    with pytest.raises(PlcEventSequenceError, match="duplicate"):
        duplicate.poll()

    gap = _adapter([_snapshot(_event(20)), _snapshot(_event(22), heartbeat=2)])
    gap.poll()
    with pytest.raises(PlcEventSequenceError, match="gap"):
        gap.poll()


def test_rejects_stale_heartbeat() -> None:
    adapter = _adapter([_snapshot(), _snapshot(sequence=2)], clock=[0.0, 2.0])
    assert adapter.poll() == ()
    with pytest.raises(StalePlcHeartbeatError):
        adapter.poll()


def test_rejects_plc_overflow() -> None:
    adapter = _adapter([_snapshot(overflow=True)])

    with pytest.raises(PlcFifoOverflowError, match="overflow"):
        adapter.poll()


def test_retries_inconsistent_snapshot_then_accepts_consistent_read() -> None:
    transport = FakeTransport(
        [_snapshot(sequence=5, sequence_after=6), _snapshot(_event(7), sequence=7)]
    )
    adapter = ModbusTcpTriggerAdapter(transport, ModbusTcpTriggerConfig(enabled=True))

    assert adapter.poll()[0].sequence == 7
    assert transport.calls == 2


def test_rejects_snapshot_that_remains_inconsistent_after_retry() -> None:
    adapter = _adapter(
        [_snapshot(sequence=1, sequence_after=2), _snapshot(sequence=3, sequence_after=4)]
    )

    with pytest.raises(InconsistentPlcSnapshotError):
        adapter.poll()
