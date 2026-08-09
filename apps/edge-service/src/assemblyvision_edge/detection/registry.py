"""Process-wide read-only model weight cache (E4c, ADR-013 Phase 3).

Several inspection instances may reference the same immutable model artifact;
the registry shares one loaded model handle per (artifact checksum, device) so
per-instance pipelines do not reload identical weights. The cache stores only
read-only model handles: detectors keep their own settings and never share
mutable inference state (E4 task invariant 6).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from assemblyvision_domain.models import ModelManifest


class ModelRegistry:
    """Thread-safe cache of loaded model weights keyed by artifact + device.

    ``load`` returns the cached model together with the inference lock shared
    by every holder of that handle. Ultralytics YOLO instances keep mutable
    predictor state during ``predict``, so concurrent inference threads must
    serialize per shared model; distinct models remain parallel (E4 invariant
    6: the cache never shares mutable inference state across instances).
    """

    def __init__(self) -> None:
        self._models: dict[str, tuple[Any, threading.Lock]] = {}
        self._lock = threading.Lock()

    def load(self, key: str, factory: Callable[[], Any]) -> tuple[Any, threading.Lock]:
        """Return the cached (model, inference lock) for ``key``, loading once."""
        with self._lock:
            entry = self._models.get(key)
            if entry is None:
                entry = (factory(), threading.Lock())
                self._models[key] = entry
            return entry

    def size(self) -> int:
        with self._lock:
            return len(self._models)

    def clear(self) -> None:
        with self._lock:
            self._models.clear()


def model_weight_key(manifest: ModelManifest, device: str | None) -> str:
    """Cache key binding the immutable artifact checksum to the device.

    Distinct artifacts are never merged because the key is the artifact SHA-256
    (falling back to the model version identity), and devices are separated so
    a CPU and a GPU instance of the same weights never share a handle.
    """
    if manifest.artifacts:
        checksum = manifest.artifacts[0].sha256
    else:
        checksum = (
            manifest.model_version_label
            if manifest.model_version_label is not None
            else str(manifest.model_version_id)
        )
    return f"{checksum}:{device or 'default'}"
