"""Edge runtime state shared by the local API (device/camera/inspection state).

Holds the inspection pipeline, the operational pause state, and the camera
placeholder. The pipeline is optional: when configuration or model weights are
unavailable the service still serves history, health, and configuration while
reporting ``inspection_ready`` false (design 16.11).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from assemblyvision_domain.errors import ConfigError

from assemblyvision_edge.api.settings import ServerSettings

log = logging.getLogger("assemblyvision.runtime")

_LOW_DISK_WARNING_BYTES = 5 * 1024**3


class EdgeRuntime:
    """Mutable runtime snapshot and optional inspection pipeline."""

    def __init__(self, settings: ServerSettings) -> None:
        self._settings = settings
        self.pipeline: Any = None
        self.pipeline_error: str | None = None
        self.device_id: UUID = self._resolve_device_id(settings.device_id)
        self.paused = False
        self.paused_reason: str | None = None
        self.paused_by: str | None = None
        self.paused_at: str | None = None
        self.rule_snapshot: dict[str, Any] | None = None

    @staticmethod
    def _resolve_device_id(configured: str | None) -> UUID:
        if configured:
            return UUID(configured)
        return uuid4()

    def load_pipeline(self) -> None:
        """Build the inspection pipeline from configuration; failures are non-fatal."""
        if self._settings.config_path is None or self._settings.rule_path is None:
            self.pipeline_error = "pipeline configuration or rule path is not configured"
            log.warning("%s", self.pipeline_error)
            return
        try:
            self.pipeline = _build_pipeline(self._settings)
            self.pipeline_error = None
        except (ConfigError, ValueError) as exc:
            self.pipeline_error = str(exc)
            self.pipeline = None
            log.error("pipeline build failed: %s", exc)

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
        if self.pipeline is None:
            operational = "FAULTED" if self.pipeline_error else "INITIALIZING"
            inspection_ready = False
        else:
            operational = "PAUSED" if self.paused else "READY"
            inspection_ready = not self.paused
        try:
            import shutil

            disk_free = shutil.disk_usage(self._settings.output_root).free
        except OSError:
            disk_free = 0
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
            "sync_ready": False,
            "camera_connected": True,
            "model_loaded": self.pipeline is not None,
            "central_connected": False,
            "disk_free_bytes": disk_free,
            "upload_pending_count": upload_pending,
            "current_product_model_version_id": self._model_version_id("product"),
            "current_component_model_version_id": self._model_version_id("component"),
            "current_rule_version_id": None,
            "alerts": alerts,
        }

    def _model_version_id(self, task: str) -> str | None:
        if self.pipeline is None:
            return None
        manifest = (
            self.pipeline._product_manifest
            if task == "product"
            else self.pipeline._component_manifest
        )
        return str(manifest.model_version_id)

    def inspection_state(self, last_result: str | None) -> dict[str, Any]:
        return {
            "window_active": False,
            "paused": self.paused,
            "faulted": self.pipeline is None,
            "current_inspection_id": None,
            "last_result": last_result,
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


def _build_pipeline(settings: ServerSettings) -> Any:
    """Build the inspection pipeline exactly as the CLI does (shared logic)."""
    from assemblyvision_domain.models import ModelManifest
    from assemblyvision_vision.manifests import load_model_manifest
    from assemblyvision_vision.roi.roi_engine import ROIEngine

    from assemblyvision_edge.config import load_pipeline_config, load_rule_definition
    from assemblyvision_edge.detection import ComponentDetector, ProductDetector
    from assemblyvision_edge.pipeline import InspectionPipeline
    from assemblyvision_edge.rules.rule_engine import RuleEngine

    if settings.config_path is None or settings.rule_path is None:
        raise ConfigError("pipeline configuration and rule path are required")
    config = load_pipeline_config(settings.config_path)
    rule = load_rule_definition(settings.rule_path)
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
