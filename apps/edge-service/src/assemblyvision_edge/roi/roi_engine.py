"""ROI engine: turn a product bounding box into a validated product ROI."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from PIL import Image

from assemblyvision_edge.domain import reason_codes as rc
from assemblyvision_edge.domain.errors import ROIGenerationError
from assemblyvision_edge.domain.models import BoundingBox, ROIResult
from assemblyvision_edge.roi.geometry import (
    Box,
    clip,
    expand,
    retained_fraction,
    translation_transform,
)


@dataclass(frozen=True)
class ROIConfig:
    """ROI generation parameters."""

    margin_x_ratio: float = 0.05
    margin_y_ratio: float = 0.05
    min_area_pixels: int = 250_000
    min_expanded_area_retained: float = 0.90
    normalize_perspective: bool = False

    def __post_init__(self) -> None:
        if not (0.0 <= self.margin_x_ratio < 1.0):
            raise ROIGenerationError("margin_x_ratio must be in [0, 1)")
        if not (0.0 <= self.margin_y_ratio < 1.0):
            raise ROIGenerationError("margin_y_ratio must be in [0, 1)")
        if self.min_area_pixels <= 0:
            raise ROIGenerationError("min_area_pixels must be positive")
        if not (0.0 < self.min_expanded_area_retained <= 1.0):
            raise ROIGenerationError("min_expanded_area_retained must be in (0, 1]")
        if self.normalize_perspective:
            raise ROIGenerationError("perspective normalization is not supported by the static MVP")


@dataclass(frozen=True)
class GeneratedROI:
    """A generated product ROI image together with its metadata."""

    roi_image: Image.Image
    result: ROIResult


class ROIEngine:
    """Generates and validates a product ROI from a product bounding box."""

    def __init__(self, config: ROIConfig) -> None:
        self._config = config

    def generate(self, frame: Image.Image, frame_id: UUID, product_box: BoundingBox) -> GeneratedROI:
        box = Box.from_bbox(product_box)
        margin_x = box.width * self._config.margin_x_ratio
        margin_y = box.height * self._config.margin_y_ratio
        expanded = expand(box, margin_x, margin_y)
        clipped = clip(expanded, float(frame.width), float(frame.height))
        if clipped.area < self._config.min_area_pixels:
            raise ROIGenerationError(rc.ROI_INVALID)
        if retained_fraction(expanded, clipped) < self._config.min_expanded_area_retained:
            raise ROIGenerationError(rc.ROI_INVALID)
        left, top = int(round(clipped.x_min)), int(round(clipped.y_min))
        right, bottom = int(round(clipped.x_max)), int(round(clipped.y_max))
        if not (0 <= left < right <= frame.width and 0 <= top < bottom <= frame.height):
            raise ROIGenerationError(rc.ROI_INVALID)
        roi_image = frame.crop((left, top, right, bottom))
        result = ROIResult(
            frame_id=frame_id,
            product_bbox=product_box,
            roi_bbox=clipped.to_bbox(frame.width, frame.height),
            roi_width=roi_image.width,
            roi_height=roi_image.height,
            orientation_degrees=None,
            transform_full_to_roi=translation_transform(float(left), float(top)),
            media_id=None,
        )
        return GeneratedROI(roi_image=roi_image, result=result)
