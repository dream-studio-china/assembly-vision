"""Tests for component dataset preparation (pure remap logic)."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_training.prepare_components import _remap_labels


def test_remap_identity_transform(tmp_path: Path) -> None:
    lbl = tmp_path / "labels.txt"
    lbl.write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    transform = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    result = _remap_labels(lbl, 100, 100, transform)
    assert len(result) == 1
    parts = result[0].split()
    assert float(parts[1]) == pytest.approx(0.5)
    assert float(parts[2]) == pytest.approx(0.5)


def test_remap_with_translation(tmp_path: Path) -> None:
    lbl = tmp_path / "labels.txt"
    lbl.write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    transform = (1.0, 0.0, -30.0, 0.0, 1.0, -20.0)
    result = _remap_labels(lbl, 100, 100, transform)
    assert len(result) == 1
    parts = result[0].split()
    roi_cx = float(parts[1])
    roi_cy = float(parts[2])
    assert 0.15 < roi_cx < 0.25
    assert 0.25 < roi_cy < 0.35


def test_remap_drops_boxes_outside_roi(tmp_path: Path) -> None:
    lbl = tmp_path / "labels.txt"
    lbl.write_text("0 0.05 0.05 0.1 0.1\n", encoding="utf-8")
    transform = (1.0, 0.0, -30.0, 0.0, 1.0, -20.0)
    result = _remap_labels(lbl, 100, 100, transform)
    assert len(result) == 0


def test_remap_empty_label_file(tmp_path: Path) -> None:
    lbl = tmp_path / "labels.txt"
    lbl.write_text("", encoding="utf-8")
    result = _remap_labels(lbl, 100, 100, (1.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    assert len(result) == 0
