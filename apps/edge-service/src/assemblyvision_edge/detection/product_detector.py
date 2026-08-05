"""Stage-one product detector adapter (Ultralytics YOLO)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.errors import ConfigError, DetectionError
from assemblyvision_domain.models import (
    BoundingBox,
    FrameQuality,
    ModelManifest,
    ProductDetection,
)
from assemblyvision_vision.manifests import resolve_artifact_path
from PIL import Image

from assemblyvision_edge.config import DetectionSettings
from assemblyvision_edge.detection.raw import extract_raw

PRODUCT_CLASS = "product"


@dataclass(frozen=True)
class ProductDetectionOutcome:
    """Result of a stage-one product detection attempt."""

    selected: ProductDetection | None = None
    reason_code: str | None = None
    candidates: tuple[ProductDetection, ...] = field(default_factory=tuple)


class ProductDetector:
    """Detects the product in a full frame and selects one unambiguous product."""

    def __init__(self, manifest: ModelManifest, settings: DetectionSettings, model: Any) -> None:
        if manifest.task != "PRODUCT_DETECTION":
            raise ConfigError(f"manifest task {manifest.task!r} is not PRODUCT_DETECTION")
        missing_classes = {PRODUCT_CLASS} - set(manifest.class_names)
        if missing_classes:
            raise ConfigError(
                f"manifest class_names missing configured product classes: {sorted(missing_classes)}"
            )
        self._manifest = manifest
        self._settings = settings
        self._model = model

    @classmethod
    def from_manifest(
        cls,
        manifest: ModelManifest,
        settings: DetectionSettings,
        manifest_path: Any,
    ) -> ProductDetector:
        from ultralytics import YOLO  # type: ignore[attr-defined]

        weights = resolve_artifact_path(manifest, manifest_path)
        if not weights.is_file():
            raise ConfigError(f"product weights not found: {weights}")
        model = YOLO(str(weights))
        return cls(manifest, settings, model)

    def detect(self, frame: Image.Image, frame_id: UUID) -> ProductDetectionOutcome:
        try:
            results: Any = self._model(frame, verbose=False)
        except Exception as exc:
            raise DetectionError(rc.INFERENCE_ERROR, f"product inference failed: {exc}") from exc
        if not results:
            return ProductDetectionOutcome(reason_code=rc.NO_PRODUCT)

        candidates = [
            (cls_id, conf, xyxy)
            for cls_id, conf, xyxy in extract_raw(results[0].boxes)
            if cls_id < len(self._manifest.class_names)
            and self._manifest.class_names[cls_id] == PRODUCT_CLASS
            and conf >= self._settings.confidence_threshold
        ]
        if not candidates:
            return ProductDetectionOutcome(reason_code=rc.NO_PRODUCT)
        if len(candidates) > 1:
            return ProductDetectionOutcome(reason_code=rc.MULTIPLE_PRODUCTS)

        cls_id, conf, (x1, y1, x2, y2) = candidates[0]
        bbox = BoundingBox(
            x_min=x1, y_min=y1, x_max=x2, y_max=y2,
            image_width=frame.width, image_height=frame.height,
        )
        selected = ProductDetection(
            frame_id=frame_id,
            product_class=self._manifest.class_names[cls_id],
            confidence=conf,
            bbox=bbox,
            model_version_id=self._manifest.model_version_id,
            quality=FrameQuality(usable=True, blur_score=0.0, brightness_mean=0.0, saturation_fraction=0.0),
        )
        return ProductDetectionOutcome(selected=selected, candidates=(selected,))
