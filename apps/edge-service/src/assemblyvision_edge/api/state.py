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
from assemblyvision_edge.persistence.repository import EdgeRepository, RepositoryError

log = logging.getLogger("assemblyvision.runtime")

_LOW_DISK_WARNING_BYTES = 5 * 1024**3
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
    last_result: str | None = None
    thread: threading.Thread | None = None


def _instance_device_id(instance: InstanceConfig) -> UUID:
    """Stable per-instance device identity (uuid5) unless explicitly set."""
    if instance.device_id is not None:
        return UUID(instance.device_id)
    return uuid5(_INSTANCE_NAMESPACE, instance.instance_id)


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
        self._stop = threading.Event()
        self._preview_cache: dict[str, tuple[float, bytes]] = {}

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

        try:
            edge_config = load_edge_config(Path(config_path))
        except ConfigError as exc:
            self.pipeline_error = str(exc)
            self.pipeline_error_code = "CONFIG_INVALID"
            self.instances = {}
            log.error("edge configuration failed: %s", exc)
            return
        registry = repository.register_rule_identity if repository is not None else None
        instances: dict[str, InstanceRuntime] = {}
        sources: dict[str, Any] = {}
        unavailable: dict[str, str] = {}
        for instance in edge_config.instances:
            pipeline: Any = None
            pipeline_error: str | None = None
            try:
                pipeline = _build_instance_pipeline(instance, rule_registry=registry)
            except (ConfigError, ValueError, RepositoryError) as exc:
                pipeline_error = str(exc)
                log.error("instance %s pipeline build failed: %s", instance.instance_id, exc)
            instances[instance.instance_id] = InstanceRuntime(
                instance_id=instance.instance_id,
                device_id=_instance_device_id(instance),
                pipeline=pipeline,
                pipeline_error=pipeline_error,
                inspection_enabled=instance.inspection.enabled,
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

    def _inspection_loop(self, instance_id: str) -> None:
        """Consume the per-instance inspection queue (one inspection per frame).

        Each queued frame is inspected exactly once; frames captured while
        paused are drained and never processed as evidence (PR-014 F1/F2).
        """
        from assemblyvision_edge.output.writer import OutputWriter

        runtime = self.instances.get(instance_id)
        if runtime is None or runtime.pipeline is None or self.camera_manager is None:
            return
        writer = OutputWriter(self._settings.output_root)
        was_paused = self.paused
        while not self._stop.is_set():
            if self.paused:
                if not was_paused:
                    log.warning("inspection paused for instance %s", instance_id)
                self.camera_manager.drain_inspection(instance_id)
                was_paused = True
                time.sleep(0.05)
                continue
            if was_paused:
                # Resuming: drop stale frames captured during the pause window.
                self.camera_manager.drain_inspection(instance_id)
                was_paused = False
            frame = self.camera_manager.next_frame(instance_id, timeout=0.1)
            if frame is None:
                continue
            try:
                record = runtime.pipeline.inspect_frame(frame, writer)
                runtime.last_result = record.decision.business_result
            except Exception:  # noqa: BLE001 - loop must survive frame errors
                log.exception("inspection failed for instance %s", instance_id)

    def pause(self, reason: str, by: str = "operator") -> None:
        self.paused = True
        self.paused_reason = reason
        self.paused_by = by
        self.paused_at = datetime.now(UTC).isoformat()

    def resume(self) -> None:
        self.paused = False
        self.paused_reason = None
        self.paused_by = None
        self.paused_at = None

    def device_status(self, upload_pending: int) -> dict[str, Any]:
        """Assemble the DeviceStatus snapshot (design 15.3.1)."""
        if self.instances:
            return self._device_status_instances(upload_pending)
        return self._device_status_single(upload_pending)

    def _device_status_single(self, upload_pending: int) -> dict[str, Any]:
        if self.pipeline is None:
            operational = "FAULTED" if self.pipeline_error else "INITIALIZING"
            inspection_ready = False
        else:
            operational = "PAUSED" if self.paused else "READY"
            inspection_ready = not self.paused
        disk_free = self._disk_free_bytes()
        alerts: list[str] = []
        if not inspection_ready:
            alerts.append("NOT_READY")
        if disk_free < _LOW_DISK_WARNING_BYTES:
            alerts.append("DISK_LOW")
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
            "disk_free_bytes": disk_free,
            "upload_pending_count": upload_pending,
            "current_product_model_version_id": self._model_version_id(self.pipeline, "product"),
            "current_component_model_version_id": self._model_version_id(
                self.pipeline, "component"
            ),
            "current_rule_version_id": None,
            "alerts": alerts,
        }

    def _device_status_instances(self, upload_pending: int) -> dict[str, Any]:
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
        disk_free = self._disk_free_bytes()
        alerts: list[str] = []
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
        if disk_free < _LOW_DISK_WARNING_BYTES:
            alerts.append("DISK_LOW")
        first_ready = next((iid for iid in ready_pipelines if iid in connected), None)
        pipeline = self.instances[first_ready].pipeline if first_ready else None
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
            "disk_free_bytes": disk_free,
            "upload_pending_count": upload_pending,
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
    instance: InstanceConfig, rule_registry: Callable[[str, int, str], None] | None = None
) -> Any:
    """Build the inspection pipeline for one instance (ADR-013)."""
    from assemblyvision_domain.models import ModelManifest
    from assemblyvision_vision.manifests import load_model_manifest
    from assemblyvision_vision.roi.roi_engine import ROIEngine

    from assemblyvision_edge.config import (
        RuleIdentityRegistry,
        load_rule_definition,
        validate_model_version_declaration,
        validate_rule_component_compatibility,
    )
    from assemblyvision_edge.detection import ComponentDetector, ProductDetector
    from assemblyvision_edge.pipeline import InspectionPipeline
    from assemblyvision_edge.rules.rule_engine import RuleEngine

    config = instance.pipeline
    registry: RuleIdentityRegistry | None = rule_registry
    rule = load_rule_definition(instance.rule, registry=registry)
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
        device_id=_instance_device_id(instance),
    )
