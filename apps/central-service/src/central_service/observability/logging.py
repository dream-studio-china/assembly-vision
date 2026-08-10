"""Structured logging setup and request correlation for the central server."""

from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging with a consistent, bounded format."""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
