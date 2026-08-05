"""Pure ROI geometry helpers with no image I/O."""

from __future__ import annotations

from dataclasses import dataclass

from assemblyvision_domain.models import BoundingBox

Transform = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class Box:
    """Unconstrained axis-aligned rectangle used during geometry math."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @classmethod
    def from_bbox(cls, bbox: BoundingBox) -> Box:
        return cls(bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max)

    def to_bbox(self, image_width: int, image_height: int) -> BoundingBox:
        return BoundingBox(
            x_min=self.x_min,
            y_min=self.y_min,
            x_max=self.x_max,
            y_max=self.y_max,
            image_width=image_width,
            image_height=image_height,
        )

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def area(self) -> float:
        return self.width * self.height


def expand(box: Box, margin_x: float, margin_y: float) -> Box:
    """Expand a box by absolute pixel margins."""
    return Box(
        box.x_min - margin_x,
        box.y_min - margin_y,
        box.x_max + margin_x,
        box.y_max + margin_y,
    )


def clip(box: Box, width: float, height: float) -> Box:
    """Clip a box to the image bounds [0, width] x [0, height]."""
    return Box(
        max(0.0, min(box.x_min, width)),
        max(0.0, min(box.y_min, height)),
        max(0.0, min(box.x_max, width)),
        max(0.0, min(box.y_max, height)),
    )


def retained_fraction(expanded: Box, clipped: Box) -> float:
    """Fraction of the expanded box area retained after clipping."""
    if expanded.area <= 0:
        return 0.0
    return clipped.area / expanded.area


def translation_transform(offset_x: float, offset_y: float) -> Transform:
    """Affine transform mapping full-frame to ROI coordinates."""
    return (1.0, 0.0, -offset_x, 0.0, 1.0, -offset_y)


def inverse_transform(transform: Transform) -> Transform:
    """Inverse of a translation-only affine transform (ROI to full-frame)."""
    a, b, c, d, e, f = transform
    return (a, b, -c, d, e, -f)


def apply_transform(box: Box, transform: Transform) -> Box:
    """Apply a 2D affine transform to a box."""
    a, b, c, d, e, f = transform
    return Box(
        a * box.x_min + b * box.y_min + c,
        d * box.x_min + e * box.y_min + f,
        a * box.x_max + b * box.y_max + c,
        d * box.x_max + e * box.y_max + f,
    )
