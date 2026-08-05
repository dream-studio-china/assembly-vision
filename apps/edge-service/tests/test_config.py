"""Tests for configuration and manifest loading."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_edge.config import load_pipeline_config, load_rule_definition
from assemblyvision_edge.domain.errors import ConfigError
from assemblyvision_edge.manifests import load_model_manifest

from tests.conftest import COMPONENT_MANIFEST, EXAMPLE_PIPELINE, EXAMPLE_RULE, PRODUCT_MANIFEST


def test_load_example_pipeline_config() -> None:
    config = load_pipeline_config(EXAMPLE_PIPELINE)
    assert config.application_version == "0.1.0"
    assert config.product_manifest.is_file()
    assert config.component_manifest.is_file()
    assert set(config.components) == {"manual", "component_a", "component_b"}


def test_load_example_rule() -> None:
    rule = load_rule_definition(EXAMPLE_RULE)
    assert rule.rule_id == "model-a-presence"
    assert rule.rule_version == 3
    assert set(rule.required_components) == {"component_a", "component_b", "manual"}


def test_load_example_manifests() -> None:
    product = load_model_manifest(PRODUCT_MANIFEST)
    component = load_model_manifest(COMPONENT_MANIFEST)
    assert product.task == "PRODUCT_DETECTION"
    assert component.task == "COMPONENT_DETECTION"
    assert "manual" in component.class_names


def test_invalid_config_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("models:\n  product_manifest: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_pipeline_config(path)


def test_missing_config_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_pipeline_config(tmp_path / "missing.yaml")


def test_invalid_rule_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad-rule.yaml"
    path.write_text("schema_version: 1\nrule_version: 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_rule_definition(path)


def test_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_model_manifest(tmp_path / "missing.json")
