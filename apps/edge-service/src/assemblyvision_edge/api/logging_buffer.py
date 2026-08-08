"""Log capture: a bounded in-memory ring buffer fed by the logging system."""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import UTC, datetime


class LogEvent:
    """One captured structured log event."""

    def __init__(self, record: logging.LogRecord) -> None:
        self.logged_at: str = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        self.level: str = record.levelname
        self.component: str = record.name
        self.message: str = record.getMessage()
        self.trace_id: str | None = getattr(record, "trace_id", None)


class LogBuffer(logging.Handler):
    """Bounded structured log buffer exposed through the log API."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self._capacity = capacity
        self._buffer: deque[LogEvent] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        # Logging must never raise or crash the caller, so capture is best-effort.
        try:  # noqa: S110
            event = LogEvent(record)
            with self._lock:
                self._buffer.append(event)
        except Exception:  # noqa: S110
            pass

    def snapshot(self, limit: int = 100) -> list[LogEvent]:
        with self._lock:
            items = list(self._buffer)
        items.reverse()
        return items[:limit]
