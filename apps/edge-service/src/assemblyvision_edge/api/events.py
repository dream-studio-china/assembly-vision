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

from pydantic import BaseModel

_SCHEMA_VERSION = 1


class _Disconnect:
    """Queue sentinel that tells one slow consumer to close its socket."""


class RuntimeEventStats(BaseModel):
    """Operational counters for the runtime event channel (PR-023 F05).

    Exposed through the authenticated status surface so operators can
    distinguish an idle dashboard from a failed event feed. Counters are
    process-local and reset on restart; they never carry credentials,
    identities, or payload contents.
    """

    active_connections: int
    published_total: int
    published_by_type: dict[str, int]
    slow_consumer_disconnects: int
    delivery_failures: int


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
    instead of growing without bound. ``asyncio.Queue`` is not a cross-thread
    primitive, so the fullness decision happens only on the owning event loop
    (E4 review PR23-F02); the producer thread never touches the queue.
    """

    def __init__(self, source_id: str, *, max_buffer: int = 100) -> None:
        self._source_id = source_id
        self._max_buffer = max_buffer
        self._sequence = 0
        # Reentrant: publish() holds the lock while delivering synchronously
        # from the event-loop thread, and _deliver() re-acquires it to keep
        # the dead-queue marker consistent with the subscription map.
        self._lock = threading.RLock()
        self._subscriptions: dict[
            asyncio.Queue[EventEnvelope | _Disconnect], asyncio.AbstractEventLoop
        ] = {}
        # Queues that were handed the disconnect sentinel: they must never
        # receive a normal envelope again (PR23-F02).
        self._dead: set[asyncio.Queue[EventEnvelope | _Disconnect]] = set()
        # Observable counters (PR-023 F05), all updated under the lock.
        self._published_total = 0
        self._published_by_type: dict[str, int] = {}
        self._slow_consumer_disconnects = 0
        self._delivery_failures = 0

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
            self._dead.discard(queue)

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
            self._published_total += 1
            self._published_by_type[event_type] = self._published_by_type.get(event_type, 0) + 1
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
                if queue in self._dead:
                    continue
                if running_loop is loop:
                    # Publishing from the loop thread: deliver synchronously so
                    # the bounded-buffer decision sees current queue state.
                    self._deliver(queue, envelope)
                else:
                    # Cross-thread publish: schedule one callback that performs
                    # the fullness decision on the owning loop. Never inspect
                    # or mutate the queue here; the loop may fill between the
                    # check and the write (PR23-F02). A closing loop drops the
                    # subscription instead of raising into the publisher.
                    try:
                        loop.call_soon_threadsafe(self._deliver, queue, envelope)
                    except RuntimeError:
                        self._delivery_failures += 1
                        self._dead.add(queue)
                        self._subscriptions.pop(queue, None)
        return envelope

    def _deliver(
        self,
        queue: asyncio.Queue[EventEnvelope | _Disconnect],
        envelope: EventEnvelope,
    ) -> None:
        """Deliver one envelope on the owning loop, disconnecting full consumers."""
        if queue in self._dead:
            return
        if queue.full():
            with self._lock:
                self._dead.add(queue)
                self._slow_consumer_disconnects += 1
            self._drop_slow_consumer(queue)
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

    def stats(self) -> RuntimeEventStats:
        """Snapshot the process-local channel counters (PR-023 F05)."""
        with self._lock:
            return RuntimeEventStats(
                active_connections=len(self._subscriptions),
                published_total=self._published_total,
                published_by_type=dict(self._published_by_type),
                slow_consumer_disconnects=self._slow_consumer_disconnects,
                delivery_failures=self._delivery_failures,
            )
