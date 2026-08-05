"""Raw detection extraction from Ultralytics result boxes."""

from __future__ import annotations

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
        xyxy = boxes.xyxy[i]
        x1, y1, x2, y2 = (float(v) for v in xyxy)
        raw.append((int(boxes.cls[i]), float(boxes.conf[i]), (x1, y1, x2, y2)))
    return raw
