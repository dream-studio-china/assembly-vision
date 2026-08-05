"""Stage-two component detector adapter (scaffold stub)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from PIL import Image

from assemblyvision_edge.config import ComponentDetectionSettings, DetectionSettings
from assemblyvision_edge.domain import reason_codes as rc
from assemblyvision_edge.domain.errors import ConfigError, DetectionError
from assemblyvision_edge.domain.models import ComponentDetection, ModelManifest

SCAFFOLD_MESSAGE = (
    "detector is a scaffold stub; supply a trained YOLO artifact and weights "
    "referenced by the model manifest (models/manifests)"
)


class ComponentDetector:
    """Placeholder component detector.

    Validates the manifest and required component settings at construction and
    raises DetectionError at inference time until a real artifact is wired in.
    """

    def __init__(
        self,
        manifest: ModelManifest,
        settings: DetectionSettings,
        components: dict[str, ComponentDetectionSettings],
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

    @classmethod
    def from_manifest(
        cls,
        manifest: ModelManifest,
        settings: DetectionSettings,
        components: dict[str, ComponentDetectionSettings],
    ) -> ComponentDetector:
        return cls(manifest, settings, components)

    def detect(
        self,
        roi: Image.Image,
        frame_id: UUID,
        required: Sequence[str],
    ) -> list[ComponentDetection]:
        raise DetectionError(rc.INFERENCE_ERROR, SCAFFOLD_MESSAGE)
