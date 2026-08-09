"""In-memory runtime event bus for the edge WebSocket channel (E4a).

Implements the design 15.5/15.6 boundary: WebSocket events are transient
notifications only; REST remains authoritative. The bus assigns a monotonic
sequence per ``(source_id, channel)``, keeps a bounded per-connection buffer,
and disconnects consumers that fall behind instead of blocking publishers, so
inspection, persistence, and the upload worker are never stalled by event
delivery (E4 task invariant 2).
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

_SCHEMA_VERSION = 1


class _Disconnect:
    """Queue sentinel that tells one slow consumer to close its socket."""


@dataclass(frozen=True)
class EventEnvelope:
    """One design 15.6 event envelope."""

    event_id: str
    type: str
    schema_version: int
    occurred_at: str
    source_id: str
    sequence: int
    correlation_id: str | None
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeEventBus:
    """Thread-safe event publisher with bounded per-connection queues.

    ``publish`` is synchronous and non-blocking: envelopes are scheduled onto
    each subscribed connection's asyncio queue via ``call_soon_threadsafe``,
    so callers on inspection/worker threads never wait on consumers. A
    consumer whose queue is full is drained and handed the disconnect sentinel
    instead of growing without bound.
    """

    def __init__(self, source_id: str, *, max_buffer: int = 100) -> None:
        self._source_id = source_id
        self._max_buffer = max_buffer
        self._sequence = 0
        self._lock = threading.Lock()
        self._subscriptions: dict[
            asyncio.Queue[EventEnvelope | _Disconnect], asyncio.AbstractEventLoop
        ] = {}

    def subscribe(
        self, loop: asyncio.AbstractEventLoop
    ) -> asyncio.Queue[EventEnvelope | _Disconnect]:
        """Register one connection; returns its bounded event queue."""
        queue: asyncio.Queue[EventEnvelope | _Disconnect] = asyncio.Queue(maxsize=self._max_buffer)
        with self._lock:
            self._subscriptions[queue] = loop
        return queue

    def unsubscribe(self, queue: asyncio.Queue[EventEnvelope | _Disconnect]) -> None:
        with self._lock:
            self._subscriptions.pop(queue, None)

    @property
    def connection_count(self) -> int:
        with self._lock:
            return len(self._subscriptions)

    @property
    def last_sequence(self) -> int:
        with self._lock:
            return self._sequence

    def publish(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> EventEnvelope:
        """Publish one envelope to every subscribed connection (non-blocking)."""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        with self._lock:
            self._sequence += 1
            envelope = EventEnvelope(
                event_id=str(uuid4()),
                type=event_type,
                schema_version=_SCHEMA_VERSION,
                occurred_at=datetime.now(UTC).isoformat(),
                source_id=self._source_id,
                sequence=self._sequence,
                correlation_id=correlation_id,
                data=data,
            )
            for queue, loop in list(self._subscriptions.items()):
                if running_loop is loop:
                    # Publishing from the loop thread: deliver synchronously so
                    # the bounded-buffer check sees current queue state.
                    self._deliver(queue, envelope)
                elif queue.full():
                    loop.call_soon_threadsafe(self._drop_slow_consumer, queue)
                else:
                    loop.call_soon_threadsafe(queue.put_nowait, envelope)
        return envelope

    @classmethod
    def _deliver(
        cls,
        queue: asyncio.Queue[EventEnvelope | _Disconnect],
        envelope: EventEnvelope,
    ) -> None:
        """Deliver one envelope, disconnecting the consumer when the buffer is full."""
        if queue.full():
            cls._drop_slow_consumer(queue)
        else:
            queue.put_nowait(envelope)

    @staticmethod
    def _drop_slow_consumer(
        queue: asyncio.Queue[EventEnvelope | _Disconnect],
    ) -> None:
        """Discard buffered events for a slow consumer and signal disconnect."""
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(_Disconnect())
