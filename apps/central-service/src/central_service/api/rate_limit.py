"""Bounded in-process rate limiting for the pilot API (C6).

A per-client fixed sliding window over a bounded hit deque. The pilot runs a
single stateless API instance, so an in-process limiter is sufficient;
distributed limits belong to the production hardening scope. Requests that
exceed the window are rejected with ``429`` and a ``Retry-After`` hint; health
endpoints are never limited so orchestrator probes cannot be starved.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class RateLimitState:
    """Sliding-window hit tracker keyed by client identity."""

    limit_per_minute: int
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque), repr=False)

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Decide one request from ``key``.

        Returns ``(allowed, retry_after_seconds)``; when the window is full,
        ``retry_after`` is a bounded estimate of when the oldest hit expires.
        """
        now = time.monotonic() if now is None else now
        window_seconds = 60.0
        hits = self._hits[key]
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= self.limit_per_minute:
            retry_after = max(1, int(window_seconds - (now - hits[0])) + 1)
            return False, retry_after
        hits.append(now)
        return True, 0

    def reset(self) -> None:
        """Clear all windows (used by tests)."""
        self._hits.clear()


def client_key(request_host: str | None, forwarded_for: str | None) -> str:
    """A stable per-client key without trusting arbitrary hop chains.

    The first ``X-Forwarded-For`` value (the immediate client) is used when
    present; otherwise the socket peer address stands in. The value is bounded
    to avoid unbounded key growth from hostile headers.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first and len(first) <= 64:
            return f"xff:{first}"
    return f"peer:{request_host or 'unknown'}"
