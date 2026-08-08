"""Per-instance camera source lifecycle, latest-frame cache, and inspection queue.

The manager owns one capture thread per configured instance; each thread
consumes the instance's :class:`FrameSource` stream and retains only the
latest captured frame for preview so memory stays bounded regardless of frame
rate. Instances subscribed for inspection additionally feed a bounded queue;
when the queue is saturated the newest frame is dropped and the overflow is
recorded explicitly (``frames_dropped``/``degraded``) instead of being lost
silently (PR-014 F1). A failing instance is reported (non-fatal) without
affecting the others.
"""

from __future__ import annotations

import logging
import queue
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

_DEFAULT_QUEUE_MAXSIZE = 8


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
    inspection_queue: queue.Queue[CapturedFrame] | None = field(default=None, repr=False)
    frames_dropped: int = 0
    degraded: bool = False


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
        return tuple(self._states)

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

    def register_unavailable(self, instance_id: str, code: str, message: str) -> None:
        """Record an instance whose source could not be constructed (non-fatal)."""
        if instance_id not in self._states:
            self._states[instance_id] = InstanceSourceState(instance_id)
        self._mark_error(instance_id, code, message)

    def subscribe_inspection(self, instance_id: str, maxsize: int = _DEFAULT_QUEUE_MAXSIZE) -> None:
        """Enable a bounded inspection queue for one instance (PR-014 F1)."""
        state = self._states.get(instance_id)
        if state is not None and state.inspection_queue is None:
            state.inspection_queue = queue.Queue(maxsize=maxsize)

    def next_frame(self, instance_id: str, timeout: float = 0.1) -> CapturedFrame | None:
        """Return the oldest queued inspection frame, or None on timeout."""
        state = self._states.get(instance_id)
        if state is None or state.inspection_queue is None:
            return None
        try:
            return state.inspection_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain_inspection(self, instance_id: str) -> int:
        """Discard queued frames as documented overflow; returns the count.

        Used when inspection is paused so stale frames are never processed as
        new evidence (PR-014 F2); the dropped frames are recorded as the
        explicit overflow/degraded condition.
        """
        state = self._states.get(instance_id)
        if state is None or state.inspection_queue is None:
            return 0
        dropped = 0
        while True:
            try:
                state.inspection_queue.get_nowait()
            except queue.Empty:
                break
            dropped += 1
        if dropped:
            with self._lock:
                state.frames_dropped += dropped
                state.degraded = True
        return dropped

    def _capture_loop(self, instance_id: str) -> None:
        source = self._sources[instance_id]
        try:
            for frame in source.frames(self._stop):
                self._publish_frame(instance_id, frame)
        except FrameStreamError as exc:
            self._mark_error(instance_id, "CAMERA_STREAM_ERROR", str(exc))
        except AssemblyVisionError as exc:
            self._mark_error(instance_id, "CAMERA_STREAM_ERROR", str(exc))
        except Exception as exc:  # noqa: BLE001 - final unexpected-exception handler
            log.exception("camera instance %s capture loop failed unexpectedly", instance_id)
            self._mark_error(instance_id, "CAMERA_STREAM_ERROR", f"unexpected capture error: {exc}")
        else:
            if not self._stop.is_set():
                self._mark_error(instance_id, "STREAM_ENDED", "camera stream ended")

    def _publish_frame(self, instance_id: str, frame: CapturedFrame) -> None:
        state = self._states[instance_id]
        with self._lock:
            state.last_frame = frame
            state.last_frame_at = frame.wall_clock_utc.astimezone(UTC).isoformat()
            state.connected = True
            state.error_code = None
            state.error = None
        inspection_queue = state.inspection_queue
        if inspection_queue is not None:
            try:
                inspection_queue.put_nowait(frame)
            except queue.Full:
                with self._lock:
                    state.frames_dropped += 1
                    state.degraded = True

    def _mark_error(self, instance_id: str, code: str, message: str) -> None:
        state = self._states.get(instance_id)
        if state is None:
            return
        with self._lock:
            state.connected = False
            state.error_code = code
            state.error = message
        log.warning("camera instance %s: %s: %s", instance_id, code, message)
