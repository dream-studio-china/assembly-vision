"""Per-instance camera source lifecycle and latest-frame cache (ADR-013).

The manager owns one capture thread per configured instance; each thread
consumes the instance's :class:`FrameSource` stream and retains only the
latest captured frame so memory stays bounded regardless of frame rate. A
failing instance is reported (non-fatal) without affecting the others.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC

from assemblyvision_domain.errors import AssemblyVisionError
from assemblyvision_vision.sources.frame_source import (
    CameraCapabilities,
    CapturedFrame,
    FrameSource,
    FrameStreamError,
)

log = logging.getLogger("assemblyvision.camera")


@dataclass
class InstanceSourceState:
    """Mutable per-instance source snapshot for status and preview."""

    instance_id: str
    connected: bool = False
    error_code: str | None = None
    error: str | None = None
    capabilities: CameraCapabilities | None = None
    last_frame: CapturedFrame | None = field(default=None, repr=False)
    last_frame_at: str | None = None


class CameraSourceManager:
    """Opens, consumes, and closes one frame source per instance."""

    def __init__(self, sources: dict[str, FrameSource]) -> None:
        self._sources = sources
        self._states = {instance_id: InstanceSourceState(instance_id) for instance_id in sources}
        self._threads: dict[str, threading.Thread] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def instance_ids(self) -> tuple[str, ...]:
        return tuple(self._sources)

    def start(self) -> None:
        """Open every source and start its capture thread; failures are non-fatal."""
        for instance_id, source in self._sources.items():
            state = self._states[instance_id]
            try:
                capabilities = source.open()
            except AssemblyVisionError as exc:
                self._mark_error(instance_id, "CAMERA_UNAVAILABLE", str(exc))
                continue
            with self._lock:
                state.capabilities = capabilities
                state.connected = True
                state.error_code = None
                state.error = None
            thread = threading.Thread(
                target=self._capture_loop,
                args=(instance_id,),
                name=f"camera-{instance_id}",
                daemon=True,
            )
            self._threads[instance_id] = thread
            thread.start()

    def stop(self) -> None:
        """Signal every capture thread to stop, join, and close all sources."""
        self._stop.set()
        for thread in self._threads.values():
            thread.join(timeout=5)
        for source in self._sources.values():
            try:
                source.close()
            except Exception:  # noqa: BLE001 - close must not mask shutdown
                log.warning("camera source close failed", exc_info=True)
        with self._lock:
            for state in self._states.values():
                state.connected = False

    def state(self, instance_id: str) -> InstanceSourceState | None:
        return self._states.get(instance_id)

    def latest_frame(self, instance_id: str) -> CapturedFrame | None:
        state = self._states.get(instance_id)
        return state.last_frame if state is not None else None

    def _capture_loop(self, instance_id: str) -> None:
        source = self._sources[instance_id]
        state = self._states[instance_id]
        try:
            for frame in source.frames(self._stop):
                with self._lock:
                    state.last_frame = frame
                    state.last_frame_at = frame.wall_clock_utc.astimezone(UTC).isoformat()
                    state.connected = True
                    state.error_code = None
                    state.error = None
        except FrameStreamError as exc:
            self._mark_error(instance_id, "CAMERA_STREAM_ERROR", str(exc))
        except AssemblyVisionError as exc:
            self._mark_error(instance_id, "CAMERA_STREAM_ERROR", str(exc))
        finally:
            if not self._stop.is_set():
                self._mark_error(instance_id, "STREAM_ENDED", "camera stream ended")

    def _mark_error(self, instance_id: str, code: str, message: str) -> None:
        state = self._states.get(instance_id)
        if state is None:
            return
        with self._lock:
            state.connected = False
            state.error_code = code
            state.error = message
        log.warning("camera instance %s: %s: %s", instance_id, code, message)
