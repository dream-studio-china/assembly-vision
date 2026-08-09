"""Lazy Harvester access for GigE Vision frame sources.

Harvester (and its ``genicam`` GenTL bindings) is an optional dependency
(``vision-core[gige]``); it is imported lazily so the package loads without it.
The module is loaded through ``importlib.import_module`` so static typing never
depends on Harvester stubs.
"""

from __future__ import annotations

import importlib
from typing import Any

from assemblyvision_vision.sources.frame_source import FrameStreamError

_harvester: Any | None = None


def get_harvester() -> Any:
    """Return the ``harvesters.core`` module, raising a clear error when unavailable."""
    global _harvester
    if _harvester is None:
        try:
            _harvester = importlib.import_module("harvesters.core")
        except ImportError as exc:
            raise FrameStreamError(
                "Harvester is required for GigE Vision frame sources; "
                "install vision-core with the 'gige' extra"
            ) from exc
    return _harvester
