"""Lazy OpenCV access and BGR-to-RGB conversion for frame sources.

OpenCV is an optional dependency (``vision-core[video]``), so it is imported
lazily with a clear error instead of failing at module import time.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from assemblyvision_vision.sources.frame_source import FrameStreamError

_cv2: Any | None = None


def get_cv2() -> Any:
    """Return the OpenCV module, raising a clear error when unavailable."""
    global _cv2
    if _cv2 is None:
        try:
            import cv2
        except ImportError as exc:
            raise FrameStreamError(
                "OpenCV is required for video and device frame sources; "
                "install vision-core with the 'video' extra"
            ) from exc
        _cv2 = cv2
    return _cv2


def to_pil_rgb(bgr: Any) -> Image.Image:
    """Convert an OpenCV BGR numpy frame to a PIL RGB image."""
    cv2 = get_cv2()
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)
