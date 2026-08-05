"""Raw detection extraction from Ultralytics result boxes."""

from __future__ import annotations

import math
from typing import Any

RawDetection = tuple[int, float, tuple[float, float, float, float]]


def extract_raw(boxes: Any) -> list[RawDetection]:
    """Extract ``(class_id, confidence, xyxy)`` tuples from result boxes.

    Works for both real Ultralytics tensors and test doubles that expose
    indexable ``cls``, ``conf``, and ``xyxy`` attributes.
    """
    raw: list[RawDetection] = []
    if boxes is None:
        return raw
    for i in range(len(boxes)):
        class_id = float(boxes.cls[i])
        confidence = float(boxes.conf[i])
        x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i])
        if not math.isfinite(class_id) or not class_id.is_integer() or class_id < 0:
            raise ValueError(f"detection {i} has an invalid class ID")
        if not math.isfinite(confidence):
            raise ValueError(f"detection {i} has a non-finite confidence")
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
            raise ValueError(f"detection {i} has non-finite coordinates")
        raw.append((int(class_id), confidence, (x1, y1, x2, y2)))
    return raw
