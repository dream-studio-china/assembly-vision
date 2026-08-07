"""Tests for ROI engine validation and generation failures."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.errors import ROIGenerationError
from assemblyvision_domain.models import BoundingBox
from assemblyvision_vision.roi.roi_engine import ROIConfig, ROIEngine
from PIL import Image


@pytest.mark.parametrize(
    "kwargs",
    [
        {"margin_x_ratio": 1.5},
        {"margin_x_ratio": -0.1},
        {"margin_y_ratio": 1.5},
        {"min_area_pixels": 0},
        {"min_area_pixels": -5},
        {"min_expanded_area_retained": 0.0},
        {"min_expanded_area_retained": 1.5},
        {"normalize_perspective": True},
    ],
)
def test_roi_config_rejects_invalid(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "margin_x_ratio": 0.05,
        "margin_y_ratio": 0.05,
        "min_area_pixels": 100,
    }
    values.update(kwargs)
    with pytest.raises(ROIGenerationError):
        ROIConfig(**values)  # type: ignore[arg-type]


def test_roi_config_accepts_valid() -> None:
    config = ROIConfig(margin_x_ratio=0.1, margin_y_ratio=0.1, min_area_pixels=50)
    assert config.margin_x_ratio == 0.1


def test_roi_generation_rejects_tiny_product(tmp_path: Path) -> None:
    frame = Image.new("RGB", (100, 100), (0, 0, 0))
    box = BoundingBox(x_min=10, y_min=10, x_max=20, y_max=20, image_width=100, image_height=100)
    engine = ROIEngine(ROIConfig(min_area_pixels=10_000))
    with pytest.raises(ROIGenerationError):
        engine.generate(frame, uuid4(), box)


def test_roi_generation_rejects_edge_product(tmp_path: Path) -> None:
    # Product touching the frame edge leaves too little retained area after clipping.
    frame = Image.new("RGB", (200, 200), (0, 0, 0))
    box = BoundingBox(x_min=0, y_min=0, x_max=180, y_max=180, image_width=200, image_height=200)
    engine = ROIEngine(ROIConfig(margin_x_ratio=0.5, margin_y_ratio=0.5, min_area_pixels=1000))
    with pytest.raises(ROIGenerationError):
        engine.generate(frame, uuid4(), box)


def test_roi_generation_happy_path() -> None:
    frame = Image.new("RGB", (800, 600), (128, 128, 128))
    box = BoundingBox(x_min=100, y_min=80, x_max=700, y_max=520, image_width=800, image_height=600)
    engine = ROIEngine(ROIConfig(min_area_pixels=1000))
    generated = engine.generate(frame, uuid4(), box)
    assert generated.roi_image.width == generated.result.roi_width
    assert generated.result.roi_bbox.image_width == 800


def test_roi_generation_rejects_rounding_collapse() -> None:
    # A sub-pixel-width product survives the area check but collapses to a
    # zero-width crop after rounding; the safety bounds check must reject it.
    frame = Image.new("RGB", (100, 100), (0, 0, 0))
    box = BoundingBox(
        x_min=0.4, y_min=0.0, x_max=0.4999, y_max=20.0, image_width=100, image_height=100
    )
    engine = ROIEngine(
        ROIConfig(
            margin_x_ratio=0.0,
            margin_y_ratio=0.0,
            min_area_pixels=1,
            min_expanded_area_retained=1.0,
        )
    )
    with pytest.raises(ROIGenerationError):
        engine.generate(frame, uuid4(), box)
