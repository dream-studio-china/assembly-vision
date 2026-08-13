"""Bounded in-process rate limiting for the pilot API (C6).

A per-client fixed sliding window over a bounded hit deque. The pilot runs a
single stateless API instance, so an in-process limiter is sufficient;
distributed limits belong to the production hardening scope. Requests that
exceed the window are rejected with ``429`` and a ``Retry-After`` hint; health
endpoints are never limited so orchestrator probes cannot be starved.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from ipaddress import ip_address


@dataclass
class RateLimitState:
    """Sliding-window hit tracker keyed by client identity."""

    limit_per_minute: int
    max_keys: int = 10_000
    _hits: OrderedDict[str, deque[float]] = field(default_factory=OrderedDict, repr=False)

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Decide one request from ``key``.

        Returns ``(allowed, retry_after_seconds)``; when the window is full,
        ``retry_after`` is a bounded estimate of when the oldest hit expires.
        """
        now = time.monotonic() if now is None else now
        window_seconds = 60.0
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._hits.popitem(last=False)
            hits = deque()
            self._hits[key] = hits
        else:
            self._hits.move_to_end(key)
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
    """Return a bounded key from one proxy-written IP address or the socket peer.

    The Compose proxy overwrites ``X-Forwarded-For`` with its observed peer
    address. Comma-separated chains and non-IP values are rejected so a direct
    caller cannot choose arbitrary limiter identities.
    """
    if forwarded_for and "," not in forwarded_for:
        candidate = forwarded_for.strip()
        try:
            normalized = str(ip_address(candidate))
        except ValueError:
            pass
        else:
            return f"xff:{normalized}"
    return f"peer:{request_host or 'unknown'}"
