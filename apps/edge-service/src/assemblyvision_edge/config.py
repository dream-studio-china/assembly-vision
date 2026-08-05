"""Pipeline configuration loading and validation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from assemblyvision_domain.errors import ConfigError
from assemblyvision_domain.models import ModelManifest
from assemblyvision_vision.manifests import manifest_model_version
from assemblyvision_vision.roi.roi_engine import ROIConfig

from assemblyvision_edge.rules.rule_engine import RuleDefinition


def validate_model_version_declaration(declared: str, manifest: ModelManifest, name: str) -> None:
    """Bind a pipeline-declared model version to the loaded manifest identity.

    The free-form version string in the configuration must match the canonical
    label recorded in (or derivable from) the manifest; otherwise an
    incompatible model/rule pairing could be loaded and evaluated as valid.
    """
    expected = manifest_model_version(manifest)
    if declared != expected:
        raise ConfigError(f"{name} {declared!r} does not match loaded manifest version {expected!r}")


@dataclass(frozen=True)
class DetectionSettings:
    """Shared detector settings."""

    model_version: str
    confidence_threshold: float
    iou_threshold: float


@dataclass(frozen=True)
class ComponentDetectionSettings:
    """Per-component observation threshold."""

    observation_threshold: float


@dataclass(frozen=True)
class PipelineConfig:
    """Resolved pipeline configuration."""

    application_version: str
    product_manifest: Path
    component_manifest: Path
    product_detection: DetectionSettings
    component_detection: DetectionSettings
    components: dict[str, ComponentDetectionSettings]
    roi: ROIConfig


def _require_mapping(section: Any, name: str) -> dict[str, Any]:
    if not isinstance(section, dict):
        raise ConfigError(f"configuration section {name!r} must be a mapping")
    return section


def _resolve_path(base: Path, raw: Any, name: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ConfigError(f"{name} must be a non-empty path")
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return path


def _as_number(raw: Any, name: str) -> float:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise ConfigError(f"{name} must be a number")
    value = float(raw)
    if not math.isfinite(value):
        raise ConfigError(f"{name} must be finite")
    return value


def _as_threshold(raw: Any, name: str, default: float) -> float:
    value = _as_number(raw if raw is not None else default, name)
    if not (0.0 <= value <= 1.0):
        raise ConfigError(f"{name} must be within [0, 1]")
    return value


def _as_positive_int(raw: Any, name: str, default: int) -> int:
    value = raw if raw is not None else default
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def _as_bool(raw: Any, name: str, default: bool) -> bool:
    value = raw if raw is not None else default
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be a boolean")
    return value


def _reject_unknown(section: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = set(section) - allowed
    if unknown:
        raise ConfigError(f"unknown keys in {name}: {sorted(unknown)}")


def load_pipeline_config(path: Path) -> PipelineConfig:
    """Load and validate a pipeline configuration YAML file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot load pipeline configuration: {path}: {exc}") from exc
    doc = _require_mapping(raw, "pipeline configuration")
    _reject_unknown(
        doc,
        {"application_version", "models", "product_detection", "component_detection", "roi"},
        "pipeline configuration",
    )
    base = path.parent
    application_version = doc.get("application_version", "0.1.0")
    if not isinstance(application_version, str) or not application_version:
        raise ConfigError("application_version must be a non-empty string")
    models = _require_mapping(doc.get("models"), "models")
    _reject_unknown(models, {"product_manifest", "component_manifest"}, "models")
    product_manifest = _resolve_path(base, models.get("product_manifest"), "models.product_manifest")
    component_manifest = _resolve_path(base, models.get("component_manifest"), "models.component_manifest")
    product_detection_raw = _require_mapping(doc.get("product_detection"), "product_detection")
    component_detection_raw = _require_mapping(doc.get("component_detection"), "component_detection")
    _reject_unknown(
        product_detection_raw,
        {"model_version", "confidence_threshold", "iou_threshold"},
        "product_detection",
    )
    _reject_unknown(
        component_detection_raw,
        {"model_version", "iou_threshold", "components"},
        "component_detection",
    )
    product_detection = DetectionSettings(
        model_version=_require_str(product_detection_raw.get("model_version"), "product_detection.model_version"),
        confidence_threshold=_as_threshold(
            product_detection_raw.get("confidence_threshold"), "product_detection.confidence_threshold", 0.7
        ),
        iou_threshold=_as_threshold(
            product_detection_raw.get("iou_threshold"), "product_detection.iou_threshold", 0.5
        ),
    )
    component_detection = DetectionSettings(
        model_version=_require_str(component_detection_raw.get("model_version"), "component_detection.model_version"),
        confidence_threshold=0.0,
        iou_threshold=_as_threshold(
            component_detection_raw.get("iou_threshold"), "component_detection.iou_threshold", 0.5
        ),
    )
    components_raw = _require_mapping(component_detection_raw.get("components"), "component_detection.components")
    components: dict[str, ComponentDetectionSettings] = {}
    for code, settings_raw in components_raw.items():
        settings = _require_mapping(settings_raw, f"component_detection.components.{code}")
        _reject_unknown(settings, {"observation_threshold"}, f"component_detection.components.{code}")
        components[code] = ComponentDetectionSettings(
            observation_threshold=_as_threshold(
                settings.get("observation_threshold"),
                f"component_detection.components.{code}.observation_threshold",
                0.5,
            )
        )
    if not components:
        raise ConfigError("component_detection.components must declare at least one component")
    roi_raw = _require_mapping(doc.get("roi"), "roi")
    _reject_unknown(
        roi_raw,
        {
            "margin_x_ratio",
            "margin_y_ratio",
            "min_area_pixels",
            "min_expanded_area_retained",
            "normalize_perspective",
        },
        "roi",
    )
    try:
        roi = ROIConfig(
            margin_x_ratio=_as_number(roi_raw.get("margin_x_ratio", 0.05), "roi.margin_x_ratio"),
            margin_y_ratio=_as_number(roi_raw.get("margin_y_ratio", 0.05), "roi.margin_y_ratio"),
            min_area_pixels=_as_positive_int(
                roi_raw.get("min_area_pixels"), "roi.min_area_pixels", 250000
            ),
            min_expanded_area_retained=_as_number(
                roi_raw.get("min_expanded_area_retained", 0.90), "roi.min_expanded_area_retained"
            ),
            normalize_perspective=_as_bool(
                roi_raw.get("normalize_perspective"), "roi.normalize_perspective", False
            ),
        )
    except ConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"roi configuration is invalid: {exc}") from exc
    return PipelineConfig(
        application_version=application_version,
        product_manifest=product_manifest,
        component_manifest=component_manifest,
        product_detection=product_detection,
        component_detection=component_detection,
        components=components,
        roi=roi,
    )


def _require_str(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ConfigError(f"{name} must be a non-empty string")
    return raw


def load_rule_definition(path: Path) -> RuleDefinition:
    """Load and validate a product rule definition YAML file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot load rule definition: {path}: {exc}") from exc
    try:
        return RuleDefinition.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"invalid rule definition {path}: {exc}") from exc
