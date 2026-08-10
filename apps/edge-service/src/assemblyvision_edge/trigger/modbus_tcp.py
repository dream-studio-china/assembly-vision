"""Generic, opt-in Modbus TCP FIFO trigger adapter.

This module deliberately has no live Modbus client dependency or runtime
integration. A site-specific transport can implement :class:`ModbusTcpTransport`
with a Modbus library after its PLC register profile is validated.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol


class TriggerReadMode(StrEnum):
    """Supported PLC trigger acquisition modes."""

    FIFO_SNAPSHOT = "fifo_snapshot"
    COIL_POLL = "coil_poll"


class PlcTriggerEventType(StrEnum):
    """Product-window events supplied by the PLC FIFO."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ABORT = "ABORT"


@dataclass(frozen=True)
class PlcFifoEvent:
    """One sequenced PLC event with its PLC-provided product correlation token."""

    sequence: int
    event_type: PlcTriggerEventType
    product_token: str

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("PLC event sequence must be non-negative")
        if not self.product_token:
            raise ValueError("PLC event product token must be non-empty")


@dataclass(frozen=True)
class PlcFifoSnapshot:
    """One PLC FIFO read bracketed by sequence reads for consistency checking."""

    sequence_before: int
    events: tuple[PlcFifoEvent, ...]
    heartbeat: int
    overflow: bool
    sequence_after: int

    def __post_init__(self) -> None:
        if self.sequence_before < 0 or self.sequence_after < 0:
            raise ValueError("PLC snapshot sequence must be non-negative")
        if self.heartbeat < 0:
            raise ValueError("PLC heartbeat must be non-negative")


@dataclass(frozen=True)
class PlcFifoSnapshotProfile:
    """Validated PLC contract for atomic register-snapshot trigger reads.

    The register layout is deliberately supplied by a site-specific transport.
    Coil edge polling cannot preserve the FIFO ordering or product token and is
    therefore rejected.
    """

    read_mode: TriggerReadMode = TriggerReadMode.FIFO_SNAPSHOT
    maximum_events: int = 32

    def __post_init__(self) -> None:
        if self.read_mode is not TriggerReadMode.FIFO_SNAPSHOT:
            raise ValueError("Modbus TCP triggers require FIFO snapshot reads, not coil polling")
        if self.maximum_events < 1:
            raise ValueError("PLC FIFO maximum_events must be at least 1")


@dataclass(frozen=True)
class ModbusTcpTriggerConfig:
    """Local adapter settings; disabled unless explicitly enabled by a future composition root."""

    enabled: bool = False
    snapshot_consistency_retries: int = 1
    heartbeat_timeout_s: float = 5.0
    profile: PlcFifoSnapshotProfile = PlcFifoSnapshotProfile()

    def __post_init__(self) -> None:
        if self.snapshot_consistency_retries < 0:
            raise ValueError("snapshot consistency retries must be non-negative")
        if self.heartbeat_timeout_s <= 0:
            raise ValueError("PLC heartbeat timeout must be positive")


class ModbusTcpTransport(Protocol):
    """Site adapter that returns one complete PLC FIFO register snapshot."""

    def read_fifo_snapshot(self, profile: PlcFifoSnapshotProfile) -> PlcFifoSnapshot: ...


class ModbusTcpTriggerError(RuntimeError):
    """Base error for a Modbus TCP trigger validation failure."""


class PlcFifoOverflowError(ModbusTcpTriggerError):
    """The PLC reported lost FIFO events; no event is safe to consume."""


class StalePlcHeartbeatError(ModbusTcpTriggerError):
    """The PLC heartbeat did not advance within the configured timeout."""


class InconsistentPlcSnapshotError(ModbusTcpTriggerError):
    """The FIFO changed while it was being read on every allowed attempt."""


class PlcEventSequenceError(ModbusTcpTriggerError):
    """The PLC FIFO event sequence was duplicated, reversed, or discontinuous."""


class ModbusTcpTriggerAdapter:
    """Read validated FIFO trigger events through an injected Modbus transport."""

    def __init__(
        self,
        transport: ModbusTcpTransport,
        config: ModbusTcpTriggerConfig | None = None,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._transport = transport
        self._config = config or ModbusTcpTriggerConfig()
        self._clock = clock
        self._last_event_sequence: int | None = None
        self._last_heartbeat: int | None = None
        self._last_heartbeat_at: float | None = None

    def poll(self) -> tuple[PlcFifoEvent, ...]:
        """Return the next ordered FIFO events, or no events while disabled."""
        if not self._config.enabled:
            return ()

        snapshot = self._read_consistent_snapshot()
        if snapshot.overflow:
            raise PlcFifoOverflowError("PLC FIFO overflow reported; event history is incomplete")
        if len(snapshot.events) > self._config.profile.maximum_events:
            raise PlcFifoOverflowError("PLC FIFO snapshot exceeds its configured capacity")

        now = self._clock()
        self._validate_heartbeat(snapshot.heartbeat, now)
        self._validate_event_sequences(snapshot.events)

        if snapshot.events:
            self._last_event_sequence = snapshot.events[-1].sequence
        return snapshot.events

    def _read_consistent_snapshot(self) -> PlcFifoSnapshot:
        for _ in range(self._config.snapshot_consistency_retries + 1):
            snapshot = self._transport.read_fifo_snapshot(self._config.profile)
            if snapshot.sequence_before == snapshot.sequence_after:
                return snapshot
        raise InconsistentPlcSnapshotError("PLC FIFO changed during every snapshot read")

    def _validate_heartbeat(self, heartbeat: int, now: float) -> None:
        if self._last_heartbeat != heartbeat:
            self._last_heartbeat = heartbeat
            self._last_heartbeat_at = now
            return
        if (
            self._last_heartbeat_at is not None
            and now - self._last_heartbeat_at >= self._config.heartbeat_timeout_s
        ):
            raise StalePlcHeartbeatError("PLC heartbeat is stale")

    def _validate_event_sequences(self, events: tuple[PlcFifoEvent, ...]) -> None:
        previous = self._last_event_sequence
        for event in events:
            if previous is not None:
                if event.sequence <= previous:
                    raise PlcEventSequenceError("PLC FIFO event sequence is duplicate or reversed")
                if event.sequence != previous + 1:
                    raise PlcEventSequenceError("PLC FIFO event sequence has a gap")
            previous = event.sequence
