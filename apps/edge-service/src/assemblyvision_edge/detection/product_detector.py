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
from assemblyvision_vision.manifests import verify_manifest_artifact, verify_model_class_map
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

    def __init__(
        self,
        manifest: ModelManifest,
        settings: DetectionSettings,
        model: Any,
        device: str | None = None,
    ) -> None:
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
        self._device = device

    @classmethod
    def from_manifest(
        cls,
        manifest: ModelManifest,
        settings: DetectionSettings,
        manifest_path: Any,
        device: str | None = None,
        registry: Any = None,
    ) -> ProductDetector:
        from ultralytics import YOLO  # type: ignore[attr-defined]

        from assemblyvision_edge.detection.registry import model_weight_key

        weights = verify_manifest_artifact(manifest, manifest_path)
        if registry is not None:
            # E4c: share one read-only model handle per artifact across
            # instances that reference the same manifest.
            model = registry.load(model_weight_key(manifest, device), lambda: YOLO(str(weights)))
        else:
            model = YOLO(str(weights))
        verify_model_class_map(model.names, manifest)
        return cls(manifest, settings, model, device)

    @property
    def effective_settings(self) -> dict[str, object]:
        """Effective inference parameters persisted as inference metadata.

        Ultralytics interprets a two-element ``imgsz`` as ``[height, width]``,
        so the manifest width/height are serialized in that order.
        """
        return {
            "imgsz": [self._manifest.input_height, self._manifest.input_width],
            "conf": self._settings.confidence_threshold,
            "iou": self._settings.iou_threshold,
            "device": self._device,
        }

    def detect(self, frame: Image.Image, frame_id: UUID) -> ProductDetectionOutcome:
        try:
            results: Any = self._model(
                frame,
                imgsz=(self._manifest.input_height, self._manifest.input_width),
                conf=self._settings.confidence_threshold,
                iou=self._settings.iou_threshold,
                device=self._device,
                verbose=False,
            )
            if not results:
                return ProductDetectionOutcome(reason_code=rc.NO_PRODUCT)

            candidates = [
                (cls_id, conf, xyxy)
                for cls_id, conf, xyxy in extract_raw(results[0].boxes)
                if 0 <= cls_id < len(self._manifest.class_names)
                and self._manifest.class_names[cls_id] == PRODUCT_CLASS
                and conf >= self._settings.confidence_threshold
            ]
            if not candidates:
                return ProductDetectionOutcome(reason_code=rc.NO_PRODUCT)
            if len(candidates) > 1:
                return ProductDetectionOutcome(reason_code=rc.MULTIPLE_PRODUCTS)

            cls_id, conf, (x1, y1, x2, y2) = candidates[0]
            bbox = BoundingBox(
                x_min=x1,
                y_min=y1,
                x_max=x2,
                y_max=y2,
                image_width=frame.width,
                image_height=frame.height,
            )
            selected = ProductDetection(
                frame_id=frame_id,
                product_class=self._manifest.class_names[cls_id],
                confidence=conf,
                bbox=bbox,
                model_version_id=self._manifest.model_version_id,
                quality=FrameQuality(
                    usable=True, blur_score=0.0, brightness_mean=0.0, saturation_fraction=0.0
                ),
            )
            return ProductDetectionOutcome(selected=selected, candidates=(selected,))
        except Exception as exc:
            raise DetectionError(
                rc.INFERENCE_ERROR, f"product inference output is invalid: {exc}"
            ) from exc
