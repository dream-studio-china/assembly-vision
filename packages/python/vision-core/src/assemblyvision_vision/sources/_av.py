"""Lazy PyAV access for RTSP frame sources.

PyAV is an optional dependency (``vision-core[rtsp]``); it is imported lazily
so the package loads without it. The module is loaded through
``importlib.import_module`` so static typing never depends on PyAV stubs.
"""

from __future__ import annotations

import importlib
from typing import Any

from assemblyvision_vision.sources.frame_source import FrameStreamError

_av: Any | None = None


def get_av() -> Any:
    """Return the PyAV module, raising a clear error when unavailable."""
    global _av
    if _av is None:
        try:
            _av = importlib.import_module("av")
        except ImportError as exc:
            raise FrameStreamError(
                "PyAV is required for RTSP frame sources; install vision-core with the 'rtsp' extra"
            ) from exc
    return _av
