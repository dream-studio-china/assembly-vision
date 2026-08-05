"""Stage-two component detector adapter (Ultralytics YOLO)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.errors import ConfigError, DetectionError
from assemblyvision_domain.models import BoundingBox, ComponentDetection, ModelManifest
from assemblyvision_vision.manifests import resolve_artifact_path
from assemblyvision_vision.roi.geometry import Box, apply_transform, inverse_transform
from PIL import Image

from assemblyvision_edge.config import ComponentDetectionSettings, DetectionSettings
from assemblyvision_edge.detection.raw import extract_raw


class ComponentDetector:
    """Detects required components inside a product ROI and maps boxes to full frame."""

    def __init__(
        self,
        manifest: ModelManifest,
        settings: DetectionSettings,
        components: dict[str, ComponentDetectionSettings],
        model: Any,
    ) -> None:
        if manifest.task != "COMPONENT_DETECTION":
            raise ConfigError(f"manifest task {manifest.task!r} is not COMPONENT_DETECTION")
        missing_classes = set(components) - set(manifest.class_names)
        if missing_classes:
            raise ConfigError(
                f"manifest class_names missing configured components: {sorted(missing_classes)}"
            )
        self._manifest = manifest
        self._settings = settings
        self._components = components
        self._model = model

    @classmethod
    def from_manifest(
        cls,
        manifest: ModelManifest,
        settings: DetectionSettings,
        components: dict[str, ComponentDetectionSettings],
        manifest_path: Any,
    ) -> ComponentDetector:
        from ultralytics import YOLO  # type: ignore[attr-defined]

        weights = resolve_artifact_path(manifest, manifest_path)
        if not weights.is_file():
            raise ConfigError(f"component weights not found: {weights}")
        model = YOLO(str(weights))
        return cls(manifest, settings, components, model)

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: Sequence[str],
        transform: tuple[float, float, float, float, float, float],
        frame_size: tuple[int, int],
    ) -> list[ComponentDetection]:
        """Detect required components in the ROI.

        ``transform`` maps full-frame to ROI coordinates; observations are
        mapped back to full-frame for evidence and annotation.
        """
        try:
            results: Any = self._model(roi, verbose=False)
        except Exception as exc:
            raise DetectionError(rc.INFERENCE_ERROR, f"component inference failed: {exc}") from exc
        if not results:
            return []

        frame_width, frame_height = frame_size
        inverse = inverse_transform(transform)
        observations: list[ComponentDetection] = []
        for cls_id, conf, xyxy in extract_raw(results[0].boxes):
            if cls_id >= len(self._manifest.class_names):
                continue
            code = self._manifest.class_names[cls_id]
            if code not in required:
                continue
            threshold = self._components[code].observation_threshold
            if conf < threshold:
                continue
            x1, y1, x2, y2 = xyxy
            roi_bbox = BoundingBox(
                x_min=x1, y_min=y1, x_max=x2, y_max=y2,
                image_width=roi.width, image_height=roi.height,
            )
            full_box = apply_transform(Box(x1, y1, x2, y2), inverse)
            full_bbox = full_box.to_bbox(frame_width, frame_height)
            observations.append(
                ComponentDetection(
                    frame_id=frame_id,
                    component_code=code,
                    confidence=conf,
                    roi_bbox=roi_bbox,
                    full_frame_bbox=full_bbox,
                    model_version_id=self._manifest.model_version_id,
                )
            )
        return observations
