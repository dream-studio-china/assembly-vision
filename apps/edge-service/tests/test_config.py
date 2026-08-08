"""Tests for configuration and manifest loading."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_edge.config import (
    load_pipeline_config,
    load_rule_definition,
    validate_rule_component_compatibility,
)
from assemblyvision_edge.rules.rule_engine import ComponentRequirement
from assemblyvision_vision.manifests import load_model_manifest

from tests.conftest import (
    COMPONENT_MANIFEST,
    EXAMPLE_PIPELINE,
    EXAMPLE_RULE,
    PRODUCT_MANIFEST,
    make_rule,
)


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


def _write_pipeline(tmp_path: Path, override: str) -> Path:
    path = tmp_path / "pipeline.yaml"
    base = EXAMPLE_PIPELINE.read_text(encoding="utf-8")
    path.write_text(base + "\n" + override, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "override",
    [
        "product_detection:\n  confidence_threshold: 1.5\n",
        "product_detection:\n  confidence_threshold: -0.1\n",
        "component_detection:\n  iou_threshold: nan\n",
        "component_detection:\n  components:\n    manual:\n      observation_threshold: inf\n",
        'roi:\n  normalize_perspective: "false"\n',
        "roi:\n  min_area_pixels: 100.5\n",
        "unknown_section:\n  x: 1\n",
    ],
)
def test_config_rejects_unsafe_values(tmp_path: Path, override: str) -> None:
    with pytest.raises(ConfigError):
        load_pipeline_config(_write_pipeline(tmp_path, override))


def test_config_rejects_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown keys"):
        load_pipeline_config(_write_pipeline(tmp_path, "roi:\n  margn_x_ratio: 0.1\n"))


def test_config_rejects_unknown_component_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown keys"):
        load_pipeline_config(
            _write_pipeline(
                tmp_path,
                "component_detection:\n"
                "  model_version: component-yolo-1.0.0\n"
                "  iou_threshold: 0.5\n"
                "  components:\n"
                "    manual:\n"
                "      observation_threshold: 0.5\n"
                "      threshold: 0.1\n",
            )
        )


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


def test_pipeline_section_must_be_mapping(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text("models: 42\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_pipeline_config(path)


def test_config_rejects_bool_number() -> None:
    from assemblyvision_edge.config import _as_number

    with pytest.raises(ConfigError, match="must be a number"):
        _as_number(True, "x")


def test_config_rejects_non_finite_number() -> None:
    import math

    from assemblyvision_edge.config import _as_number

    with pytest.raises(ConfigError, match="must be finite"):
        _as_number(math.inf, "x")


def test_config_rejects_threshold_out_of_range() -> None:
    from assemblyvision_edge.config import _as_threshold

    with pytest.raises(ConfigError, match="within \\[0, 1\\]"):
        _as_threshold(-0.1, "x", 0.5)


def test_config_rejects_application_version_not_string(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="application_version"):
        load_pipeline_config(_write_pipeline(tmp_path, "application_version: 123\n"))


def test_config_rejects_invalid_roi_type(tmp_path: Path) -> None:
    # normalize_perspective=true raises ROIGenerationError from ROIConfig; the
    # loader must surface it as a configuration error, not leak a raw error.
    with pytest.raises(ConfigError, match="roi configuration is invalid"):
        load_pipeline_config(_write_pipeline(tmp_path, "roi:\n  normalize_perspective: true\n"))


def test_config_wraps_roi_constructor_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _BrokenROIConfig:
        def __init__(self, **kwargs: object) -> None:
            raise ValueError("bad roi")

    monkeypatch.setattr("assemblyvision_edge.config.ROIConfig", _BrokenROIConfig)
    with pytest.raises(ConfigError, match="roi configuration is invalid"):
        load_pipeline_config(EXAMPLE_PIPELINE)


def test_load_rule_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot load rule definition"):
        load_rule_definition(tmp_path / "missing-rule.yaml")


def test_load_rule_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("schema_version: 1\n  bad: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot load rule definition"):
        load_rule_definition(path)


def test_validate_model_version_declaration_mismatch(tmp_path: Path) -> None:
    from assemblyvision_edge.config import validate_model_version_declaration

    manifest = load_model_manifest(PRODUCT_MANIFEST)
    with pytest.raises(ConfigError, match="does not match"):
        validate_model_version_declaration(
            "wrong-version", manifest, "product_detection.model_version"
        )


def test_rule_component_missing_from_config_fails_closed() -> None:
    config = load_pipeline_config(EXAMPLE_PIPELINE)
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    rule = make_rule(required_components={"ghost": ComponentRequirement(expected_count=1)})
    with pytest.raises(ConfigError, match="missing from configuration.*ghost"):
        validate_rule_component_compatibility(rule, config, manifest)


def test_incompatible_component_model_version_fails_closed() -> None:
    config = load_pipeline_config(EXAMPLE_PIPELINE)
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    rule = make_rule(compatible_component_model_versions=["component-yolo-9.9.9"])
    with pytest.raises(ConfigError, match="not in rule compatible versions"):
        validate_rule_component_compatibility(rule, config, manifest)


def test_compatible_rule_config_manifest_sets_are_accepted() -> None:
    config = load_pipeline_config(EXAMPLE_PIPELINE)
    manifest = load_model_manifest(COMPONENT_MANIFEST)
    rule = make_rule()
    # Extra manifest classes are allowed; the example rule/config agree here.
    validate_rule_component_compatibility(rule, config, manifest)
    assert "manual" in manifest.class_names
    assert "manual" in config.components


def test_rule_identity_collision_with_different_content_rejected(tmp_path: Path) -> None:
    first = tmp_path / "a.yaml"
    first.write_text(
        "schema_version: 1\n"
        "rule_id: model-a-presence\n"
        "rule_version: 5\n"
        "product_type: model_a\n"
        "compatible_component_model_versions: [component-yolo-1.0.0]\n"
        "barcode_required: false\n"
        "required_components:\n"
        "  component_a:\n"
        "    expected_count: 1\n"
        "mandatory_gates:\n"
        "  product_detected: true\n",
        encoding="utf-8",
    )
    second = tmp_path / "b.yaml"
    second.write_text(
        "schema_version: 1\n"
        "rule_id: model-a-presence\n"
        "rule_version: 5\n"
        "product_type: model_a\n"
        "compatible_component_model_versions: [component-yolo-1.0.0]\n"
        "barcode_required: false\n"
        "required_components:\n"
        "  component_a:\n"
        "    expected_count: 2\n"
        "mandatory_gates:\n"
        "  product_detected: true\n",
        encoding="utf-8",
    )
    load_rule_definition(first)
    with pytest.raises(ConfigError, match="different content"):
        load_rule_definition(second)


def test_rule_identity_same_content_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "a.yaml"
    path.write_text(EXAMPLE_RULE.read_text(encoding="utf-8"), encoding="utf-8")
    load_rule_definition(path)
    load_rule_definition(path)


def test_config_rejects_empty_components(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text(
        "application_version: '0.1.0'\n"
        "models:\n"
        "  product_manifest: m.json\n"
        "  component_manifest: c.json\n"
        "product_detection:\n"
        "  model_version: product-yolo-1.0.0\n"
        "  confidence_threshold: 0.7\n"
        "  iou_threshold: 0.5\n"
        "component_detection:\n"
        "  model_version: component-yolo-1.0.0\n"
        "  iou_threshold: 0.5\n"
        "  components: {}\n"
        "roi:\n"
        "  margin_x_ratio: 0.05\n"
        "  margin_y_ratio: 0.05\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="at least one component"):
        load_pipeline_config(path)
