"""Shared frame-source pacing helper."""

from __future__ import annotations

import time
from threading import Event


def pace(stop: Event, fps: float | None) -> None:
    """Sleep to the configured frame rate, aborting early on stop."""
    if not fps or fps <= 0:
        return
    delay = 1.0 / fps
    deadline = time.monotonic() + delay
    while time.monotonic() < deadline and not stop.is_set():
        time.sleep(min(0.01, delay))
