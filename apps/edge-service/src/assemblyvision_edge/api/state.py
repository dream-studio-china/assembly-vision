"""Edge runtime state shared by the local API (device/camera/inspection state).

Holds the inspection pipeline, the operational pause state, and the camera
placeholder. The pipeline is optional: when configuration or model weights are
unavailable the service still serves history, health, and configuration while
reporting ``inspection_ready`` false (design 16.11).
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from assemblyvision_domain.errors import AssemblyVisionError, ConfigError

from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.camera_manager import CameraSourceManager
from assemblyvision_edge.config import InstanceConfig
from assemblyvision_edge.persistence.repository import (
    EdgeRepository,
    RepositoryError,
    RetentionMetrics,
    UploadQueueMetrics,
)
from assemblyvision_edge.retention.policy import RetentionPolicy
from assemblyvision_edge.retention.storage import (
    StorageObservationError,
    StorageState,
    observe_storage,
)
from assemblyvision_edge.retention.worker import CleanupHealth
from assemblyvision_edge.upload.scheduler import SchedulerHealth

log = logging.getLogger("assemblyvision.runtime")

_INSTANCE_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
_PREVIEW_MIN_INTERVAL_S = 0.5


@dataclass
class InstanceRuntime:
    """One independent inspection instance (camera + own pipeline, ADR-013)."""

    instance_id: str
    device_id: UUID
    pipeline: Any
    pipeline_error: str | None
    inspection_enabled: bool
    temporal: Any = None
    last_result: str | None = None
    thread: threading.Thread | None = None
    correlator: Any = None


def _instance_device_id(instance: InstanceConfig) -> UUID:
    """Stable per-instance device identity (uuid5) unless explicitly set."""
    if instance.device_id is not None:
        return UUID(instance.device_id)
    return uuid5(_INSTANCE_NAMESPACE, instance.instance_id)


def _build_identity_correlator(trigger: Any) -> Any:
    """Build the per-instance trigger/identity correlator (E4b).

    Returns None when the instance has no trigger source. Only the explicit
    mock source is available until hardware trigger/barcode sources land (E6).
    """
    if trigger is None:
        return None
    from assemblyvision_edge.trigger.source import IdentityCorrelator, MockTriggerSource

    return IdentityCorrelator(MockTriggerSource(trigger.products))


class EdgeRuntime:
    """Mutable runtime snapshot and optional inspection pipeline."""

    def __init__(self, settings: ServerSettings) -> None:
        self._settings = settings
        self.pipeline: Any = None
        self.pipeline_error: str | None = None
        self.pipeline_error_code: str | None = None
        self.device_id: UUID = self._resolve_device_id(settings.device_id)
        self.paused = False
        self.paused_reason: str | None = None
        self.paused_by: str | None = None
        self.paused_at: str | None = None
        self.rule_snapshot: dict[str, Any] | None = None
        self.instances: dict[str, InstanceRuntime] = {}
        self.camera_manager: Any = None
        self.repository: Any = None
        # E4a: optional in-memory event bus; set by the API composition root so
        # inspection/device/upload transitions can notify dashboards without
        # the runtime ever depending on the channel (REST stays authoritative).
        self.event_bus: Any = None
        # E4c: process-wide read-only model weight cache shared by instances
        # that reference the same immutable artifact (ADR-013 Phase 3).
        self.model_registry: Any = None
        self._stop = threading.Event()
        self._preview_cache: dict[str, tuple[float, bytes]] = {}
        # E2c disk-pressure state: refreshed by the inspection loop and by the
        # device-status routes; a measurement/write failure fails closed.
        self._storage_settings = settings.storage
        self.storage_state: StorageState | None = None
        self.storage_write_fault = False
        # Latched at startup when the integrity scan finds faults (PR-020 F08);
        # gates intake and readiness until documented reconciliation.
        self.storage_integrity_fault = False
        self.integrity_scan: Any = None
        self.integrity_scan_at: str | None = None
        self.integrity_scan_settings: Any = None

    @staticmethod
    def _resolve_device_id(configured: str | None) -> UUID:
        if configured:
            return UUID(configured)
        return uuid4()

    def load_pipeline(self, repository: EdgeRepository | None = None) -> None:
        """Build the inspection pipeline from configuration; failures are non-fatal.

        When a repository is available the loaded rule identity is registered
        durably, so a restarted service rejects reusing a rule identity with
        different content (PR-008 P2).
        """
        if self._settings.config_path is None or self._settings.rule_path is None:
            self.pipeline_error = "pipeline configuration or rule path is not configured"
            self.pipeline_error_code = None
            log.warning("%s", self.pipeline_error)
            return
        try:
            rule_registry = repository.register_rule_identity if repository is not None else None
            self.pipeline = _build_pipeline(self._settings, rule_registry=rule_registry)
            self.pipeline_error = None
            self.pipeline_error_code = None
        except (ConfigError, ValueError, RepositoryError) as exc:
            self.pipeline_error = str(exc)
            self.pipeline_error_code = "CONFIG_INVALID"
            self.pipeline = None
            log.error("pipeline build failed: %s", exc)

    def load_config(self, repository: EdgeRepository | None = None) -> None:
        """Load the single pipeline or the multi-instance camera configuration.

        An ``instances:`` document starts per-instance camera sources; a
        legacy flat pipeline document builds the single pipeline (ADR-013).
        """
        self.repository = repository
        config_path = self._settings.config_path
        if config_path is None:
            self.load_pipeline(repository)
            return
        try:
            from assemblyvision_edge.config import load_edge_config

            load_edge_config(config_path)
        except ConfigError:
            self.load_pipeline(repository)
            return
        self.load_instances(config_path, repository)

    def load_instances(
        self, config_path: Path | None, repository: EdgeRepository | None = None
    ) -> None:
        """Build per-instance pipelines and start camera sources (ADR-013).

        Configuration or source failures are non-fatal: instances without a
        usable pipeline or source are reported in their state while the
        remaining instances and the read-only API keep working.
        """
        if config_path is None:
            self.pipeline_error = "edge configuration path is not configured"
            self.pipeline_error_code = None
            log.warning("%s", self.pipeline_error)
            return
        from assemblyvision_vision.sources.factory import build_frame_source

        from assemblyvision_edge.config import load_edge_config

        self.repository = repository
        try:
            edge_config = load_edge_config(Path(config_path))
        except ConfigError as exc:
            self.pipeline_error = str(exc)
            self.pipeline_error_code = "CONFIG_INVALID"
            self.instances = {}
            log.error("edge configuration failed: %s", exc)
            return
        registry = repository.register_rule_identity if repository is not None else None
        if self.model_registry is None:
            from assemblyvision_edge.detection.registry import ModelRegistry

            self.model_registry = ModelRegistry()
        instances: dict[str, InstanceRuntime] = {}
        sources: dict[str, Any] = {}
        unavailable: dict[str, str] = {}
        for instance in edge_config.instances:
            pipeline: Any = None
            pipeline_error: str | None = None
            try:
                pipeline = _build_instance_pipeline(
                    instance,
                    rule_registry=registry,
                    model_registry=self.model_registry,
                )
            except (ConfigError, ValueError, RepositoryError) as exc:
                pipeline_error = str(exc)
                log.error("instance %s pipeline build failed: %s", instance.instance_id, exc)
            instances[instance.instance_id] = InstanceRuntime(
                instance_id=instance.instance_id,
                device_id=_instance_device_id(instance),
                pipeline=pipeline,
                pipeline_error=pipeline_error,
                inspection_enabled=instance.inspection.enabled,
                temporal=instance.temporal,
                correlator=_build_identity_correlator(instance.trigger),
            )
            try:
                sources[instance.instance_id] = build_frame_source(
                    instance.camera.as_frame_source_config()
                )
            except AssemblyVisionError as exc:
                log.warning("instance %s camera source failed: %s", instance.instance_id, exc)
                unavailable[instance.instance_id] = str(exc)
        self.instances = instances
        self.pipeline_error = None
        self.pipeline_error_code = None
        self.camera_manager = CameraSourceManager(sources)
        for instance_id, message in unavailable.items():
            self.camera_manager.register_unavailable(instance_id, "CAMERA_UNAVAILABLE", message)
        enabled = [
            instance_id
            for instance_id, runtime in instances.items()
            if runtime.inspection_enabled
            and runtime.pipeline is not None
            and instance_id in sources
        ]
        for instance_id in enabled:
            self.camera_manager.subscribe_inspection(instance_id)
        self.camera_manager.start()
        for instance_id in enabled:
            runtime = instances[instance_id]
            runtime.thread = threading.Thread(
                target=self._inspection_loop,
                args=(instance_id,),
                name=f"inspect-{instance_id}",
                daemon=True,
            )
            runtime.thread.start()

    def shutdown(self) -> None:
        """Stop camera capture and inspection threads (ADR-013 lifecycle)."""
        self._stop.set()
        if self.camera_manager is not None:
            self.camera_manager.stop()
        for runtime in self.instances.values():
            if runtime.thread is not None:
                runtime.thread.join(timeout=5)

    def _inspection_loop(self, instance_id: str) -> None:
        """Consume the per-instance frame queue and finalize inspections.

        Instances with a temporal policy group frames into product windows and
        emit one record per window (design 10); the default single-frame mode
        emits one record per captured frame (ADR-013). Each queued frame is
        consumed exactly once; frames captured while paused are drained and
        never processed as evidence (PR-014 F1/F2).
        """
        from assemblyvision_edge.output.writer import OutputWriter
        from assemblyvision_edge.temporal.window_manager import ProductWindowManager

        runtime = self.instances.get(instance_id)
        if runtime is None or runtime.pipeline is None or self.camera_manager is None:
            return
        writer = OutputWriter(self._settings.output_root)
        window_manager = (
            ProductWindowManager(runtime.temporal, runtime.device_id)
            if runtime.temporal is not None
            else None
        )
        was_paused = self.paused
        optional = False
        while not self._stop.is_set():
            if self.paused:
                if not was_paused:
                    log.warning("inspection paused for instance %s", instance_id)
                self.camera_manager.drain_inspection(instance_id)
                was_paused = True
                time.sleep(0.05)
                continue
            self.refresh_storage()
            # A latched write fault recovers only through a mandatory
            # persistence probe, never from a successful volume observation
            # (PR-020 F05). An integrity fault gates intake until documented
            # reconciliation restarts the service (PR-020 F08).
            if self.storage_write_fault:
                self.probe_persistence()
            blocked = (
                self.storage_write_fault
                or self.storage_integrity_fault
                or (self.storage_state is not None and self.storage_state.mode == "STOP")
            )
            if blocked:
                # Stop pressure / write fault / integrity fault: durable
                # mandatory persistence cannot be guaranteed, so no new product
                # is accepted (E2 task invariant 7). Frames are drained and
                # never evaluated as evidence.
                if not was_paused:
                    log.warning(
                        "inspection intake stopped for instance %s: %s",
                        instance_id,
                        "integrity fault"
                        if self.storage_integrity_fault
                        else "storage write fault"
                        if self.storage_write_fault
                        else "storage at stop threshold (design 12.7, E2c)",
                    )
                self.camera_manager.drain_inspection(instance_id)
                was_paused = True
                time.sleep(0.5)
                continue
            optional = self._optional_capture_suppressed()
            if was_paused:
                # Resuming: drop stale frames captured during the pause window.
                self.camera_manager.drain_inspection(instance_id)
                was_paused = False
            frame = self.camera_manager.next_frame(instance_id, timeout=0.1)
            if frame is None:
                # No new frame: finalize an idle window by its capture-time gap
                # so a product at the end of a stream is decided normally
                # (PR-015 F2), then keep polling.
                if window_manager is not None:
                    try:
                        expired = window_manager.expire(time.monotonic())
                        if expired is not None:
                            record = runtime.pipeline.inspect_window(
                                expired, writer, suppress_optional_capture=optional
                            )
                            if self._persist_projection(record, instance_id):
                                runtime.last_result = record.decision.business_result
                    except Exception as exc:  # noqa: BLE001 - idle expiry must not kill the loop
                        self._note_storage_write_fault(exc)
                        log.exception("idle window expiry failed for instance %s", instance_id)
                continue
            if runtime.correlator is not None:
                # Stamp the frame with the current validated product identity
                # from the trigger source before any window grouping (E4b).
                frame = runtime.correlator.annotate(frame)
            try:
                if window_manager is not None:
                    observation = runtime.pipeline.frame_observations(frame)
                    # Group on the frame's acquisition time, not the time at
                    # which inference finished (PR-015 F3).
                    previous_id = (
                        window_manager.active_window.inspection_id
                        if window_manager.active_window is not None
                        else None
                    )
                    closed = window_manager.feed(observation, frame.monotonic_ts_ns / 1e9)
                    active = window_manager.active_window
                    if active is not None and active.inspection_id != previous_id:
                        # A new product window opened (including after a gap or
                        # identity transition closed the previous one): notify
                        # dashboards with its stable inspection id (E4a).
                        self._publish(
                            "inspection.started",
                            {
                                "inspection_id": str(active.inspection_id),
                                "instance_id": instance_id,
                            },
                            correlation_id=str(active.inspection_id),
                        )
                    if closed is not None:
                        record = runtime.pipeline.inspect_window(
                            closed, writer, suppress_optional_capture=optional
                        )
                        if self._persist_projection(record, instance_id):
                            runtime.last_result = record.decision.business_result
                else:
                    # Default per-frame mode (ADR-013): publish one start event
                    # before inference so the lifecycle matches the temporal
                    # branch. A failed inference/persistence never publishes a
                    # matching completed event (PR-023 F03); REST stays
                    # authoritative.
                    inspection_id = uuid4()
                    self._publish(
                        "inspection.started",
                        {"inspection_id": str(inspection_id), "instance_id": instance_id},
                        correlation_id=str(inspection_id),
                    )
                    identity = None
                    if getattr(runtime.pipeline, "barcode_identity_enabled", False):
                        identity = runtime.pipeline.resolve_image_identity(frame.image)
                    if identity is None:
                        record = runtime.pipeline.inspect_frame(
                            frame,
                            writer,
                            suppress_optional_capture=optional,
                            inspection_id=inspection_id,
                        )
                    else:
                        record = runtime.pipeline.inspect_frame(
                            frame,
                            writer,
                            suppress_optional_capture=optional,
                            inspection_id=inspection_id,
                            identity=identity,
                        )
                    if self._persist_projection(record, instance_id):
                        runtime.last_result = record.decision.business_result
            except Exception as exc:  # noqa: BLE001 - loop must survive frame errors
                self._note_storage_write_fault(exc)
                log.exception("inspection failed for instance %s", instance_id)
        if window_manager is not None:
            try:
                closed = window_manager.force_close()
                if closed is not None:
                    record = runtime.pipeline.inspect_window(
                        closed, writer, suppress_optional_capture=optional
                    )
                    # An interrupted close is still a published bundle; mirror
                    # it so shutdown never loses the record or its outbox tasks
                    # (PR-017 F2 residual note).
                    if self._persist_projection(record, instance_id):
                        runtime.last_result = record.decision.business_result
            except Exception:  # noqa: BLE001 - interrupted close must not mask shutdown
                log.exception("interrupted window close failed for instance %s", instance_id)

    def _publish(
        self,
        event_type: str,
        data: dict[str, object],
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Publish one transient event when a bus is configured (E4a).

        Publishing is non-blocking and never affects inspection or
        persistence; without a bus this is a no-op.
        """
        bus = self.event_bus
        if bus is not None:
            bus.publish(event_type, data, correlation_id=correlation_id)

    def _note_storage_write_fault(self, exc: Exception) -> None:
        """Latch a storage write fault from any persistence/write failure (E2c).

        A write-time failure means durable persistence cannot be guaranteed;
        the runtime fails closed (inspection_ready false, STORAGE_WRITE_FAULT)
        instead of treating the volume as healthy. Every repository/projection
        failure is treated as a persistence fault, including SQLAlchemy-wrapped
        database errors (PR-020 F01/F05).
        """
        self.storage_write_fault = True

    def _persist_projection(self, record: Any, instance_id: str | None = None) -> bool:
        """Mirror a published bundle into the SQLite projection and outbox.

        Returns True only after the projection and its upload tasks committed.
        A failure is logged and latches a storage/admission fault; the caller
        must not publish the inspection result when this returns False
        (PR-020 F01, E2 task invariant 7).
        """
        repository = self.repository
        if repository is None:
            self.storage_write_fault = True
            return False
        try:
            repository.persist_inspection_and_enqueue_uploads(
                record, retention=self._retention_policy()
            )
        except Exception as exc:  # noqa: BLE001 - projection must not break the loop
            self.storage_write_fault = True
            log.warning(
                "inspection %s was published but the projection/outbox could not be updated: %s",
                record.inspection_id,
                exc,
            )
            return False
        self._publish(
            "inspection.completed",
            {
                "inspection_id": str(record.inspection_id),
                "instance_id": instance_id,
                "business_result": record.decision.business_result,
                "internal_decision": record.decision.internal_decision,
            },
            correlation_id=str(record.inspection_id),
        )
        return True

    def _retention_policy(self) -> RetentionPolicy | None:
        """Return the approved retention policy for new media, or None."""
        retention = self._settings.retention
        if retention is None:
            return None
        return retention.to_policy()

    def _probe_output_writable(self) -> bool:
        """Probe mandatory media output by writing and fsyncing a probe file."""
        import os

        path = self._settings.output_root / ".storage-probe"
        try:
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            try:
                os.write(fd, b"probe")
                os.fsync(fd)
            finally:
                os.close(fd)
            path.unlink()
            return True
        except OSError:
            return False

    def probe_persistence(self) -> bool:
        """Mandatory-persistence recovery probe (PR-020 F05).

        Clears a latched write fault only when both the media output volume is
        writable (probe file + fsync) and the SQLite/outbox store accepts a
        write transaction. A successful volume observation alone never clears
        the latch.
        """
        from assemblyvision_edge.persistence.repository import RepositoryError

        try:
            repository_ok = self.repository is not None and self.repository.probe_writability()
        except RepositoryError:
            repository_ok = False
        if repository_ok and self._probe_output_writable():
            self.storage_write_fault = False
            return True
        return False

    def _optional_capture_suppressed(self) -> bool:
        """Return whether optional capture must be suppressed (PR-020 F07).

        At critical pressure (or worse) only explicitly optional artifacts are
        suppressed; mandatory metadata and NG evidence are always preserved.
        """
        return self.storage_state is not None and self.storage_state.mode in (
            "CRITICAL",
            "STOP",
        )

    def pause(self, reason: str, by: str = "operator") -> None:
        self.paused = True
        self.paused_reason = reason
        self.paused_by = by
        self.paused_at = datetime.now(UTC).isoformat()
        self._publish(
            "device.status_changed",
            {"paused": True, "paused_reason": reason, "paused_by": by},
        )

    def resume(self) -> None:
        self.paused = False
        self.paused_reason = None
        self.paused_by = None
        self.paused_at = None
        self._publish("device.status_changed", {"paused": False})

    def refresh_storage(self) -> StorageState | None:
        """Re-measure the output volume and update the pressure state (E2c).

        A measurement failure sets a write fault so the service fails closed
        instead of assuming healthy storage. A successful observation never
        clears a latched write fault; only :meth:`probe_persistence` may
        (PR-020 F05).
        """
        try:
            state = observe_storage(self._settings.output_root, self._storage_settings)
            self.storage_state = state
        except StorageObservationError:
            self.storage_state = None
            self.storage_write_fault = True
        return self.storage_state

    def device_status(
        self,
        upload_pending: int,
        queue: UploadQueueMetrics | None = None,
        health: SchedulerHealth | None = None,
        scheduler_enabled: bool = False,
        storage: StorageState | None = None,
        write_fault: bool | None = None,
        cleanup: CleanupHealth | None = None,
        cleanup_metrics: RetentionMetrics | None = None,
        cleanup_enabled: bool = False,
    ) -> dict[str, Any]:
        """Assemble the DeviceStatus snapshot (design 15.3.1)."""
        if queue is None:
            queue = UploadQueueMetrics(by_state={}, pending_bytes=0, oldest_pending_at=None)
        if storage is None and write_fault is None:
            storage = self.refresh_storage()
        if write_fault is None:
            write_fault = self.storage_write_fault
        if self.instances:
            return self._device_status_instances(
                upload_pending,
                queue,
                health,
                scheduler_enabled,
                storage,
                write_fault,
                cleanup,
                cleanup_metrics,
                cleanup_enabled,
            )
        return self._device_status_single(
            upload_pending,
            queue,
            health,
            scheduler_enabled,
            storage,
            write_fault,
            cleanup,
            cleanup_metrics,
            cleanup_enabled,
        )

    @staticmethod
    def _storage_status_fields(
        storage: StorageState | None,
        write_fault: bool,
        cleanup: CleanupHealth | None,
        metrics: RetentionMetrics | None,
        enabled: bool,
        integrity_scan: Any = None,
        integrity_scan_at: str | None = None,
        integrity_verify_checksums: bool = False,
        integrity_fault: bool = False,
    ) -> tuple[dict[str, Any], list[str]]:
        """Derive the storage/cleanup observability fields and alerts (E2c/E2d)."""
        mode = storage.mode if storage is not None else ("STOP" if write_fault else "NORMAL")
        fields: dict[str, Any] = {
            "storage_mode": mode,
            "storage_free_bytes": storage.free_bytes if storage else 0,
            "storage_free_percent": storage.free_percent if storage else 0.0,
            "storage_free_inodes": storage.free_inodes if storage else 0,
            "storage_inode_percent": storage.inode_free_percent if storage else 0.0,
            "storage_warning_free_percent": (storage.warning_free_percent if storage else 0.0),
            "storage_critical_free_percent": (storage.critical_free_percent if storage else 0.0),
            "storage_stop_free_percent": storage.stop_free_percent if storage else 0.0,
            "storage_observed_at": storage.observed_at if storage else None,
            "storage_write_fault": write_fault,
            "cleanup_enabled": enabled,
            "cleanup_eligible_count": metrics.eligible_count if metrics else 0,
            "cleanup_eligible_bytes": metrics.eligible_bytes if metrics else 0,
            "cleanup_deleting_count": metrics.deleting_count if metrics else 0,
            "cleanup_delete_error_count": metrics.delete_error_count if metrics else 0,
            "cleanup_purged_count": metrics.purged_count if metrics else 0,
            "cleanup_integrity_fault_count": metrics.integrity_fault_count if metrics else 0,
            "cleanup_last_run_at": cleanup.last_run_at if cleanup else None,
            "cleanup_last_error_code": cleanup.last_error_code if cleanup else None,
            "integrity_scan_last_run_at": integrity_scan_at,
            "integrity_scan_checked": integrity_scan.checked if integrity_scan else 0,
            "integrity_scan_faults": integrity_scan.faults if integrity_scan else 0,
            "integrity_scan_checksummed": (
                integrity_scan.checksum_checked if integrity_scan else 0
            ),
            "integrity_scan_skipped": integrity_scan.skipped if integrity_scan else 0,
            "integrity_scan_skipped_reason": (
                integrity_scan.skipped_reason if integrity_scan else None
            ),
            "integrity_verify_checksums": integrity_verify_checksums,
        }
        alerts: list[str] = []
        if write_fault:
            alerts.append("STORAGE_WRITE_FAULT")
        elif mode == "STOP":
            alerts.append("DISK_STOP")
        elif mode == "CRITICAL":
            alerts.append("DISK_CRITICAL")
        elif mode == "WARNING":
            alerts.append("DISK_WARNING")
        if integrity_fault or (metrics is not None and metrics.integrity_fault_count > 0):
            alerts.append("STORAGE_INTEGRITY_FAULT")
        if metrics is not None and metrics.delete_error_count > 0:
            alerts.append("CLEANUP_FAULT")
        return fields, alerts

    @staticmethod
    def _upload_status_fields(
        pending: int,
        queue: UploadQueueMetrics,
        health: SchedulerHealth | None,
        enabled: bool,
    ) -> tuple[dict[str, Any], list[str]]:
        """Derive the upload observability fields and their alerts (E1)."""
        fields: dict[str, Any] = {
            "upload_pending_count": pending,
            "upload_pending_bytes": queue.pending_bytes,
            "upload_oldest_pending_at": queue.oldest_pending_at,
            "upload_attempts": health.attempts if health else 0,
            "upload_successes": health.successes if health else 0,
            "upload_failures": health.failures if health else 0,
            "upload_failure_rate": health.failure_rate if health else 0.0,
            "upload_last_attempt_at": health.last_attempt_at if health else None,
            "upload_last_success_at": health.last_success_at if health else None,
            "upload_last_error_code": health.last_error_code if health else None,
            "upload_bytes_sent": health.bytes_sent if health else 0,
            "upload_bandwidth_mbps": health.bandwidth_mbps if health else None,
            "upload_circuit_state": health.circuit_state if health else "CLOSED",
            "upload_circuit_last_change_at": (health.circuit_last_change_at if health else None),
        }
        alerts: list[str] = []
        if pending > 0 and not enabled:
            alerts.append("UPLOAD_BLOCKED")
        elif pending > 0 and (
            queue.by_state.get("RETRY_WAIT", 0) > 0
            or (health is not None and health.attempts > 0 and health.successes == 0)
        ):
            alerts.append("UPLOAD_FAILING")
        if health is not None and health.circuit_state == "OPEN":
            alerts.append("UPLOAD_CIRCUIT_OPEN")
        return fields, alerts

    def _device_status_single(
        self,
        upload_pending: int,
        queue: UploadQueueMetrics,
        health: SchedulerHealth | None,
        scheduler_enabled: bool,
        storage: StorageState | None,
        write_fault: bool,
        cleanup: CleanupHealth | None,
        cleanup_metrics: RetentionMetrics | None,
        cleanup_enabled: bool,
    ) -> dict[str, Any]:
        if self.pipeline is None:
            operational = "FAULTED" if self.pipeline_error else "INITIALIZING"
            inspection_ready = False
        else:
            operational = "PAUSED" if self.paused else "READY"
            inspection_ready = not self.paused
        alerts: list[str] = []
        storage_fields, storage_alerts = self._storage_status_fields(
            storage,
            write_fault,
            cleanup,
            cleanup_metrics,
            cleanup_enabled,
            integrity_scan=self.integrity_scan,
            integrity_scan_at=self.integrity_scan_at,
            integrity_verify_checksums=(
                self.integrity_scan_settings.verify_checksums
                if self.integrity_scan_settings is not None
                else False
            ),
            integrity_fault=self.storage_integrity_fault,
        )
        alerts.extend(storage_alerts)
        # Stop pressure, a latched write fault, or an integrity fault means
        # mandatory persistence cannot be guaranteed: the runtime must not
        # advertise inspection readiness (E2 task invariant 7/8, PR-020 F05/F08).
        if (
            write_fault
            or self.storage_integrity_fault
            or (storage is not None and storage.mode == "STOP")
        ):
            inspection_ready = False
        if not inspection_ready:
            alerts.append("NOT_READY")
        upload_fields, upload_alerts = self._upload_status_fields(
            upload_pending, queue, health, scheduler_enabled
        )
        alerts.extend(upload_alerts)
        return {
            "device_id": str(self.device_id),
            "observed_at": datetime.now(UTC).isoformat(),
            "operational_state": operational,
            "inspection_ready": inspection_ready,
            "inspection_error_code": self.pipeline_error_code,
            "sync_ready": False,
            "camera_connected": True,
            "model_loaded": self.pipeline is not None,
            "central_connected": False,
            "disk_free_bytes": storage.free_bytes if storage else 0,
            **storage_fields,
            **upload_fields,
            "current_product_model_version_id": self._model_version_id(self.pipeline, "product"),
            "current_component_model_version_id": self._model_version_id(
                self.pipeline, "component"
            ),
            "current_rule_version_id": None,
            "alerts": alerts,
        }

    def _device_status_instances(
        self,
        upload_pending: int,
        queue: UploadQueueMetrics,
        health: SchedulerHealth | None,
        scheduler_enabled: bool,
        storage: StorageState | None,
        write_fault: bool,
        cleanup: CleanupHealth | None,
        cleanup_metrics: RetentionMetrics | None,
        cleanup_enabled: bool,
    ) -> dict[str, Any]:
        """Aggregate device status across configured instances (ADR-013)."""
        manager = self.camera_manager
        connected = [
            instance_id
            for instance_id in self.instances
            if manager is not None
            and manager.state(instance_id) is not None
            and manager.state(instance_id).connected
        ]
        ready_pipelines = [
            instance_id
            for instance_id, runtime in self.instances.items()
            if runtime.inspection_enabled and runtime.pipeline is not None
        ]
        if self.paused:
            operational = "PAUSED"
            inspection_ready = False
        else:
            inspection_ready = bool(ready_pipelines) and bool(connected)
            operational = "READY" if inspection_ready else "DEGRADED"
        alerts: list[str] = []
        storage_fields, storage_alerts = self._storage_status_fields(
            storage,
            write_fault,
            cleanup,
            cleanup_metrics,
            cleanup_enabled,
            integrity_scan=self.integrity_scan,
            integrity_scan_at=self.integrity_scan_at,
            integrity_verify_checksums=(
                self.integrity_scan_settings.verify_checksums
                if self.integrity_scan_settings is not None
                else False
            ),
            integrity_fault=self.storage_integrity_fault,
        )
        alerts.extend(storage_alerts)
        if (
            write_fault
            or self.storage_integrity_fault
            or (storage is not None and storage.mode == "STOP")
        ):
            inspection_ready = False
        if not inspection_ready:
            alerts.append("NOT_READY")
        degraded = any(
            manager is not None
            and (state := manager.state(instance_id)) is not None
            and state.degraded
            for instance_id in self.instances
        )
        if degraded:
            alerts.append("FRAME_OVERFLOW")
        first_ready = next((iid for iid in ready_pipelines if iid in connected), None)
        pipeline = self.instances[first_ready].pipeline if first_ready else None
        upload_fields, upload_alerts = self._upload_status_fields(
            upload_pending, queue, health, scheduler_enabled
        )
        alerts.extend(upload_alerts)
        return {
            "device_id": str(self.device_id),
            "observed_at": datetime.now(UTC).isoformat(),
            "operational_state": operational,
            "inspection_ready": inspection_ready,
            "inspection_error_code": None,
            "sync_ready": False,
            "camera_connected": bool(connected),
            "model_loaded": bool(ready_pipelines),
            "central_connected": False,
            "disk_free_bytes": storage.free_bytes if storage else 0,
            **storage_fields,
            **upload_fields,
            "current_product_model_version_id": self._model_version_id(pipeline, "product"),
            "current_component_model_version_id": self._model_version_id(pipeline, "component"),
            "current_rule_version_id": None,
            "alerts": alerts,
        }

    def _disk_free_bytes(self) -> int:
        import shutil

        try:
            return shutil.disk_usage(self._settings.output_root).free
        except OSError:
            return 0

    def _model_version_id(self, pipeline: Any | None, task: str) -> str | None:
        if pipeline is None:
            return None
        manifest = pipeline._product_manifest if task == "product" else pipeline._component_manifest
        return str(manifest.model_version_id)

    def inspection_state(self, last_result: str | None) -> dict[str, Any]:
        if self.instances:
            instance_last = next(
                (
                    r.last_result
                    for r in reversed(self.instances.values())
                    if r.last_result is not None
                ),
                None,
            )
            effective_last = instance_last if instance_last is not None else last_result
        else:
            effective_last = last_result
        # In multi-instance mode the single pipeline is always None; the runtime
        # is faulted only when no configured instance has a usable pipeline.
        faulted = self.pipeline is None and not any(
            r.pipeline is not None for r in self.instances.values()
        )
        return {
            "window_active": False,
            "paused": self.paused,
            "faulted": faulted,
            "current_inspection_id": None,
            "last_result": effective_last,
            "paused_reason": self.paused_reason,
            "paused_by": self.paused_by,
            "paused_at": self.paused_at,
        }

    def camera_state(self) -> dict[str, Any]:
        return {
            "connected": True,
            "source_width": self._settings.camera_width,
            "source_height": self._settings.camera_height,
            "fps": self._settings.camera_fps,
            "last_frame_at": None,
            "error_code": None,
        }

    def instance_camera_state(self, instance_id: str) -> dict[str, Any] | None:
        """Per-instance camera snapshot (ADR-013); None for unknown instances."""
        if self.camera_manager is None:
            return None
        state = self.camera_manager.state(instance_id)
        if state is None:
            return None
        capabilities = state.capabilities
        return {
            "connected": state.connected and state.last_frame is not None,
            "source_width": capabilities.source_width if capabilities else 0,
            "source_height": capabilities.source_height if capabilities else 0,
            "fps": capabilities.fps if capabilities else None,
            "last_frame_at": state.last_frame_at,
            "error_code": state.error_code,
            "camera_serial": capabilities.camera_serial if capabilities else None,
            "camera_model": capabilities.camera_model if capabilities else None,
            "firmware_version": capabilities.firmware_version if capabilities else None,
            "gentl_producer": capabilities.gentl_producer if capabilities else None,
            "transport_parent": capabilities.transport_parent if capabilities else None,
            "pixel_format": capabilities.pixel_format if capabilities else None,
            "trigger_mode": capabilities.trigger_mode if capabilities else None,
            "exposure_us": capabilities.exposure_us if capabilities else None,
            "gain_db": capabilities.gain_db if capabilities else None,
            "packet_size": capabilities.packet_size if capabilities else None,
        }

    def preview_jpeg(self, instance_id: str) -> tuple[bytes, str] | None:
        """Return (jpeg bytes, last frame time) for the latest instance frame.

        The JPEG is re-encoded at most every ``_PREVIEW_MIN_INTERVAL_S`` per
        instance so preview polling cannot saturate the CPU (ADR-013).
        """
        if self.camera_manager is None:
            return None
        state = self.camera_manager.state(instance_id)
        frame = self.camera_manager.latest_frame(instance_id)
        if state is None or frame is None:
            return None
        now = time.monotonic()
        cached = self._preview_cache.get(instance_id)
        if cached is not None and now - cached[0] < _PREVIEW_MIN_INTERVAL_S:
            return cached[1], state.last_frame_at or ""
        import io

        buffer = io.BytesIO()
        frame.image.save(buffer, format="JPEG", quality=75)
        data = buffer.getvalue()
        self._preview_cache[instance_id] = (now, data)
        return data, state.last_frame_at or ""

    def effective_configuration(self) -> dict[str, Any]:
        """Effective configuration snapshot from the loaded config/rule files."""
        managed: dict[str, Any] = {}
        if self.pipeline is not None:
            config = self.pipeline._config
            managed = {
                "application_version": config.application_version,
                "product_detection": {
                    "model_version": config.product_detection.model_version,
                    "confidence_threshold": config.product_detection.confidence_threshold,
                    "iou_threshold": config.product_detection.iou_threshold,
                },
                "component_detection": {
                    "model_version": config.component_detection.model_version,
                    "iou_threshold": config.component_detection.iou_threshold,
                    "components": {
                        code: settings.observation_threshold
                        for code, settings in config.components.items()
                    },
                },
                "roi": {
                    "margin_x_ratio": config.roi.margin_x_ratio,
                    "margin_y_ratio": config.roi.margin_y_ratio,
                    "min_area_pixels": config.roi.min_area_pixels,
                    "min_expanded_area_retained": config.roi.min_expanded_area_retained,
                    "normalize_perspective": config.roi.normalize_perspective,
                },
            }
            rule = getattr(self.pipeline, "_rule", None)
            if rule is not None:
                self.rule_snapshot = rule.model_dump(mode="json")
                managed["rule"] = {
                    "rule_id": rule.rule_id,
                    "rule_version": rule.rule_version,
                    "product_type": rule.product_type,
                    "required_components": sorted(rule.required_components),
                }
        checksum = self._config_checksum()
        return {
            "revision": "local",
            "checksum_sha256": checksum,
            "managed": managed,
            "local_overrides": {},
        }

    def _config_checksum(self) -> str:
        digest = hashlib.sha256()
        for path in (self._settings.config_path, self._settings.rule_path):
            if path is None:
                continue
            try:
                digest.update(path.read_bytes())
            except OSError:
                continue
        return digest.hexdigest()


def _build_pipeline(
    settings: ServerSettings, rule_registry: Callable[[str, int, str], None] | None = None
) -> Any:
    """Build the inspection pipeline exactly as the CLI does (shared logic)."""
    from assemblyvision_domain.models import ModelManifest
    from assemblyvision_vision.manifests import load_model_manifest
    from assemblyvision_vision.roi.roi_engine import ROIEngine

    from assemblyvision_edge.config import (
        RuleIdentityRegistry,
        load_pipeline_config,
        load_rule_definition,
        validate_rule_component_compatibility,
    )
    from assemblyvision_edge.detection import ComponentDetector, ProductDetector
    from assemblyvision_edge.pipeline import InspectionPipeline
    from assemblyvision_edge.rules.rule_engine import RuleEngine

    if settings.config_path is None or settings.rule_path is None:
        raise ConfigError("pipeline configuration and rule path are required")
    config = load_pipeline_config(settings.config_path)
    registry: RuleIdentityRegistry | None = rule_registry
    rule = load_rule_definition(settings.rule_path, registry=registry)
    product_manifest: ModelManifest = load_model_manifest(config.product_manifest)
    component_manifest: ModelManifest = load_model_manifest(config.component_manifest)
    from assemblyvision_edge.config import validate_model_version_declaration

    validate_model_version_declaration(
        config.product_detection.model_version, product_manifest, "product_detection.model_version"
    )
    validate_model_version_declaration(
        config.component_detection.model_version,
        component_manifest,
        "component_detection.model_version",
    )
    validate_rule_component_compatibility(rule, config, component_manifest)
    product_detector = ProductDetector.from_manifest(
        product_manifest, config.product_detection, config.product_manifest
    )
    component_detector = ComponentDetector.from_manifest(
        component_manifest, config.component_detection, config.components, config.component_manifest
    )
    return InspectionPipeline(
        product_detector=product_detector,
        component_detector=component_detector,
        roi_engine=ROIEngine(config.roi),
        rule_engine=RuleEngine(),
        rule=rule,
        product_manifest=product_manifest,
        component_manifest=component_manifest,
        config=config,
        device_id=UUID(str(settings.device_id or uuid4())),
    )


def _build_instance_pipeline(
    instance: InstanceConfig,
    rule_registry: Callable[[str, int, str], None] | None = None,
    model_registry: Any = None,
) -> Any:
    """Build the inspection pipeline for one instance (ADR-013).

    ``model_registry`` (E4c) lets instances that reference the same immutable
    model artifact share one read-only loaded model handle.
    """
    from assemblyvision_domain.models import ModelManifest
    from assemblyvision_vision.manifests import load_model_manifest
    from assemblyvision_vision.roi.roi_engine import ROIEngine

    from assemblyvision_edge.config import (
        RuleIdentityRegistry,
        load_rule_definition,
        validate_model_version_declaration,
        validate_rule_component_compatibility,
        validate_temporal_against_rule,
    )
    from assemblyvision_edge.detection import ComponentDetector, ProductDetector
    from assemblyvision_edge.pipeline import InspectionPipeline
    from assemblyvision_edge.rules.rule_engine import RuleEngine

    config = instance.pipeline
    registry: RuleIdentityRegistry | None = rule_registry
    rule = load_rule_definition(instance.rule, registry=registry)
    validate_temporal_against_rule(
        instance.temporal, rule, f"instance {instance.instance_id} temporal"
    )
    product_manifest: ModelManifest = load_model_manifest(config.product_manifest)
    component_manifest: ModelManifest = load_model_manifest(config.component_manifest)
    validate_model_version_declaration(
        config.product_detection.model_version, product_manifest, "product_detection.model_version"
    )
    validate_model_version_declaration(
        config.component_detection.model_version,
        component_manifest,
        "component_detection.model_version",
    )
    validate_rule_component_compatibility(rule, config, component_manifest)
    product_detector = ProductDetector.from_manifest(
        product_manifest, config.product_detection, config.product_manifest, registry=model_registry
    )
    component_detector = ComponentDetector.from_manifest(
        component_manifest,
        config.component_detection,
        config.components,
        config.component_manifest,
        registry=model_registry,
    )
    return InspectionPipeline(
        product_detector=product_detector,
        component_detector=component_detector,
        roi_engine=ROIEngine(config.roi),
        rule_engine=RuleEngine(),
        rule=rule,
        product_manifest=product_manifest,
        component_manifest=component_manifest,
        config=config,
        device_id=_instance_device_id(instance),
        temporal_config=instance.temporal,
    )
