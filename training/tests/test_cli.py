"""Tests for the av-train CLI improvement hints."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_training.cli import _print_improvement_hints


def test_component_hints_suggest_rule_bump(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rule = tmp_path / "product-rule.yaml"
    rule.write_text(
        "schema_version: 1\nrule_id: demo\nrule_version: 3\n"
        "compatible_component_model_versions: [component-yolo-0.1.0]\n",
        encoding="utf-8",
    )
    _print_improvement_hints(
        "COMPONENT_DETECTION", Path("models/weights/component-yolo-0.2.0.pt"), rule
    )
    out = capsys.readouterr().out
    assert "component_detection.model_version: 'component-yolo-0.2.0'" in out
    assert "rule_version 3 -> 4" in out
    assert "'component-yolo-0.2.0'" in out


def test_product_hints_mention_roi_regeneration(capsys: pytest.CaptureFixture[str]) -> None:
    _print_improvement_hints(
        "PRODUCT_DETECTION", Path("models/weights/product-yolo-0.2.0.pt"), None
    )
    out = capsys.readouterr().out
    assert "product_detection.model_version: 'product-yolo-0.2.0'" in out
    assert "prepare-components" in out
    assert "verify" in out
