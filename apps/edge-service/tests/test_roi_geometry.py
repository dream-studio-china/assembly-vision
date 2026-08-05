"""Tests for ROI geometry and the ROI engine."""

from __future__ import annotations

from uuid import uuid4

import pytest
from assemblyvision_edge.domain.errors import ROIGenerationError
from assemblyvision_edge.domain.models import BoundingBox
from assemblyvision_edge.roi.geometry import (
    Box,
    apply_transform,
    clip,
    expand,
    retained_fraction,
    translation_transform,
)
from assemblyvision_edge.roi.roi_engine import ROIConfig, ROIEngine
from PIL import Image


def test_expand() -> None:
    box = Box(10.0, 10.0, 50.0, 40.0)
    expanded = expand(box, 5.0, 3.0)
    assert expanded == Box(5.0, 7.0, 55.0, 43.0)


def test_clip() -> None:
    box = Box(-10.0, 5.0, 110.0, 40.0)
    clipped = clip(box, 100.0, 50.0)
    assert clipped == Box(0.0, 5.0, 100.0, 40.0)


def test_retained_fraction() -> None:
    expanded = Box(0.0, 0.0, 100.0, 100.0)
    clipped = Box(0.0, 0.0, 50.0, 100.0)
    assert retained_fraction(expanded, clipped) == pytest.approx(0.5)


def test_retained_fraction_zero_area() -> None:
    assert retained_fraction(Box(0.0, 0.0, 0.0, 0.0), Box(0.0, 0.0, 0.0, 0.0)) == 0.0


def test_transform_round_trip() -> None:
    box = Box(12.0, 20.0, 44.0, 60.0)
    transform = translation_transform(10.0, 8.0)
    moved = apply_transform(box, transform)
    assert moved == Box(2.0, 12.0, 34.0, 52.0)
    inverse = translation_transform(-10.0, -8.0)
    restored = apply_transform(moved, inverse)
    assert restored == box


def _bbox(x1: float, y1: float, x2: float, y2: float, width: int, height: int) -> BoundingBox:
    return BoundingBox(x_min=x1, y_min=y1, x_max=x2, y_max=y2, image_width=width, image_height=height)


def test_roi_engine_generates_valid_roi() -> None:
    frame = Image.new("RGB", (400, 300), (200, 200, 200))
    config = ROIConfig(
        margin_x_ratio=0.05,
        margin_y_ratio=0.05,
        min_area_pixels=10_000,
        min_expanded_area_retained=0.90,
    )
    engine = ROIEngine(config)
    product_box = _bbox(80, 60, 320, 240, 400, 300)
    generated = engine.generate(frame, uuid4(), product_box)
    assert generated.result.roi_width == 264
    assert generated.result.roi_height == 198
    assert generated.roi_image.size == (264, 198)
    assert generated.result.roi_bbox.x_min == pytest.approx(68.0)
    assert generated.result.roi_bbox.y_min == pytest.approx(51.0)


def test_roi_engine_rejects_zero_area() -> None:
    frame = Image.new("RGB", (400, 300), (200, 200, 200))
    config = ROIConfig(min_area_pixels=10_000, min_expanded_area_retained=0.90)
    engine = ROIEngine(config)
    product_box = _bbox(0, 0, 10, 10, 400, 300)
    with pytest.raises(ROIGenerationError):
        engine.generate(frame, uuid4(), product_box)


def test_roi_engine_rejects_excessive_clipping() -> None:
    frame = Image.new("RGB", (400, 300), (200, 200, 200))
    config = ROIConfig(
        margin_x_ratio=0.5,
        margin_y_ratio=0.5,
        min_area_pixels=1,
        min_expanded_area_retained=0.90,
    )
    engine = ROIEngine(config)
    product_box = _bbox(0, 0, 390, 290, 400, 300)
    with pytest.raises(ROIGenerationError):
        engine.generate(frame, uuid4(), product_box)


def test_roi_config_rejects_bad_margins() -> None:
    with pytest.raises(ROIGenerationError):
        ROIConfig(margin_x_ratio=1.5)
