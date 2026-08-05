"""Stage-one product detector adapter (scaffold stub)."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from PIL import Image

from assemblyvision_edge.config import DetectionSettings
from assemblyvision_edge.domain import reason_codes as rc
from assemblyvision_edge.domain.errors import ConfigError, DetectionError
from assemblyvision_edge.domain.models import ModelManifest, ProductDetection

SCAFFOLD_MESSAGE = (
    "detector is a scaffold stub; supply a trained YOLO artifact and weights "
    "referenced by the model manifest (models/manifests)"
)


@dataclass(frozen=True)
class ProductDetectionOutcome:
    """Result of a stage-one product detection attempt."""

    selected: ProductDetection | None = None
    reason_code: str | None = None
    candidates: tuple[ProductDetection, ...] = field(default_factory=tuple)


class ProductDetector:
    """Placeholder product detector.

    Validates the model manifest at construction and raises DetectionError at
    inference time until a real artifact is wired in.
    """

    def __init__(self, manifest: ModelManifest, settings: DetectionSettings) -> None:
        if manifest.task != "PRODUCT_DETECTION":
            raise ConfigError(f"manifest task {manifest.task!r} is not PRODUCT_DETECTION")
        allowed = {"product"}
        missing_classes = allowed - set(manifest.class_names)
        if missing_classes:
            raise ConfigError(f"manifest class_names missing configured product classes: {sorted(missing_classes)}")
        self._manifest = manifest
        self._settings = settings

    @classmethod
    def from_manifest(cls, manifest: ModelManifest, settings: DetectionSettings) -> ProductDetector:
        return cls(manifest, settings)

    def detect(self, frame: Image.Image, frame_id: UUID) -> ProductDetectionOutcome:
        raise DetectionError(rc.INFERENCE_ERROR, SCAFFOLD_MESSAGE)
