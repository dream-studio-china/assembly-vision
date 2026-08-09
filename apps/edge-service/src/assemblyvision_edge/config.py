"""Pipeline configuration loading and validation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from assemblyvision_domain.errors import ConfigError, ROIGenerationError
from assemblyvision_domain.models import ModelManifest
from assemblyvision_vision.manifests import manifest_model_version
from assemblyvision_vision.roi.roi_engine import ROIConfig
from assemblyvision_vision.sources.factory import FrameSourceConfig

from assemblyvision_edge.rules.rule_engine import RuleDefinition
from assemblyvision_edge.temporal.aggregator import (
    ComponentTemporalPolicy,
    TemporalAggregationConfig,
)
from assemblyvision_edge.trigger.source import MockProductSpec


def validate_model_version_declaration(declared: str, manifest: ModelManifest, name: str) -> None:
    """Bind a pipeline-declared model version to the loaded manifest identity.

    The free-form version string in the configuration must match the canonical
    label recorded in (or derivable from) the manifest; otherwise an
    incompatible model/rule pairing could be loaded and evaluated as valid.
    """
    expected = manifest_model_version(manifest)
    if declared != expected:
        raise ConfigError(
            f"{name} {declared!r} does not match loaded manifest version {expected!r}"
        )


def validate_rule_component_compatibility(
    rule: RuleDefinition,
    config: PipelineConfig,
    component_manifest: ModelManifest,
) -> None:
    """Fail closed when rule/configuration/manifest component sets disagree.

    A rule-required component missing from the configuration would later raise
    ``KeyError`` inside the component detector on every inspection, and a
    component-model version outside the rule's compatible set must never be
    evaluated as valid. Extra manifest classes and extra configured components
    are allowed; they are not decision evidence unless the active rule requires
    them (F8).
    """
    required = set(rule.required_components)
    configured = set(config.components)
    missing = sorted(required - configured)
    if missing:
        raise ConfigError(
            "rule requires components missing from configuration: " + ", ".join(missing)
        )
    model_version = manifest_model_version(component_manifest)
    if model_version not in rule.compatible_component_model_versions:
        raise ConfigError(
            f"component model version {model_version!r} is not in rule compatible "
            f"versions {sorted(rule.compatible_component_model_versions)}"
        )


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
    return _parse_pipeline_doc(doc, path.parent)


def _parse_pipeline_doc(doc: dict[str, Any], base: Path) -> PipelineConfig:
    """Parse and validate the pipeline sections of a configuration document."""
    application_version = doc.get("application_version", "0.1.0")
    if not isinstance(application_version, str) or not application_version:
        raise ConfigError("application_version must be a non-empty string")
    models = _require_mapping(doc.get("models"), "models")
    _reject_unknown(models, {"product_manifest", "component_manifest"}, "models")
    product_manifest = _resolve_path(
        base, models.get("product_manifest"), "models.product_manifest"
    )
    component_manifest = _resolve_path(
        base, models.get("component_manifest"), "models.component_manifest"
    )
    product_detection_raw = _require_mapping(doc.get("product_detection"), "product_detection")
    component_detection_raw = _require_mapping(
        doc.get("component_detection"), "component_detection"
    )
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
        model_version=_require_str(
            product_detection_raw.get("model_version"), "product_detection.model_version"
        ),
        confidence_threshold=_as_threshold(
            product_detection_raw.get("confidence_threshold"),
            "product_detection.confidence_threshold",
            0.7,
        ),
        iou_threshold=_as_threshold(
            product_detection_raw.get("iou_threshold"), "product_detection.iou_threshold", 0.5
        ),
    )
    component_detection = DetectionSettings(
        model_version=_require_str(
            component_detection_raw.get("model_version"), "component_detection.model_version"
        ),
        confidence_threshold=0.0,
        iou_threshold=_as_threshold(
            component_detection_raw.get("iou_threshold"), "component_detection.iou_threshold", 0.5
        ),
    )
    components_raw = _require_mapping(
        component_detection_raw.get("components"), "component_detection.components"
    )
    components: dict[str, ComponentDetectionSettings] = {}
    for code, settings_raw in components_raw.items():
        settings = _require_mapping(settings_raw, f"component_detection.components.{code}")
        _reject_unknown(
            settings, {"observation_threshold"}, f"component_detection.components.{code}"
        )
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
    except ROIGenerationError as exc:
        raise ConfigError(f"roi configuration is invalid: {exc}") from exc
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


# A rule identity is immutable once installed. The registry callback receives
# (rule_id, rule_version, content_hash) and may persist the identity durably
# (e.g. into the edge SQLite registry) so a restarted process rejects reusing
# the identity with different content.
RuleIdentityRegistry = Callable[[str, int, str], None]


def load_rule_definition(
    path: Path, registry: RuleIdentityRegistry | None = None
) -> RuleDefinition:
    """Load and validate a product rule definition YAML file.

    ``registry`` is invoked after the in-process identity check so durable
    install registries can reject content changes across processes.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot load rule definition: {path}: {exc}") from exc
    try:
        rule = RuleDefinition.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"invalid rule definition {path}: {exc}") from exc
    _register_rule_identity(rule)
    if registry is not None:
        registry(rule.rule_id, rule.rule_version, rule_content_hash(rule))
    return rule


# Process-local installed-rule registry (P2): a rule identity is immutable
# once loaded, so the same (rule_id, rule_version) cannot be reactivated with
# different content in one process. The edge service additionally persists this
# in the SQLite ``rule_identities`` table for restart safety.
_RULE_IDENTITY_REGISTRY: dict[tuple[str, int], str] = {}


def rule_content_hash(rule: RuleDefinition) -> str:
    payload = json.dumps(rule.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _register_rule_identity(rule: RuleDefinition) -> None:
    key = (rule.rule_id, rule.rule_version)
    digest = rule_content_hash(rule)
    existing = _RULE_IDENTITY_REGISTRY.get(key)
    if existing is not None and existing != digest:
        raise ConfigError(
            f"rule identity {rule.rule_id} v{rule.rule_version} was already loaded "
            "with different content; rules are immutable once loaded"
        )
    _RULE_IDENTITY_REGISTRY[key] = digest


# -- Multi-instance edge configuration (ADR-013) -------------------------------

_SOURCE_TYPES = {"folder", "video", "opencv-device", "rtsp", "http-image"}


@dataclass(frozen=True)
class CameraSourceConfig:
    """Per-instance camera source configuration (design 07.7)."""

    source: Literal["folder", "video", "opencv-device", "rtsp", "http-image"]
    path: Path | None = None
    url: str | None = None
    device: int | str | None = None
    fps: float | None = None
    loop: bool = False
    reconnect_initial_delay_ms: int = 250
    reconnect_maximum_delay_ms: int = 10000

    def as_frame_source_config(self) -> FrameSourceConfig:
        """Convert to the neutral vision-core factory configuration."""
        return FrameSourceConfig(
            source=self.source,
            path=self.path,
            url=self.url,
            device=self.device,
            fps=self.fps,
            loop=self.loop,
            reconnect_initial_delay_ms=self.reconnect_initial_delay_ms,
            reconnect_maximum_delay_ms=self.reconnect_maximum_delay_ms,
        )


@dataclass(frozen=True)
class InspectionRunConfig:
    """Whether the instance runs the inspection loop."""

    enabled: bool = False


@dataclass(frozen=True)
class TriggerSourceConfig:
    """Product-identity trigger source for an instance (E4b).

    Only the deterministic ``mock`` source is available until hardware
    triggers/barcode decoding land (E6); mock is explicitly development/
    test-only and never masquerades as production hardware.
    """

    source: Literal["mock"] = "mock"
    products: tuple[MockProductSpec, ...] = ()


@dataclass(frozen=True)
class InstanceConfig:
    """One independent inspection instance (camera + own pipeline/rule)."""

    instance_id: str
    device_id: str | None
    camera: CameraSourceConfig
    inspection: InspectionRunConfig
    temporal: TemporalAggregationConfig | None
    pipeline: PipelineConfig
    rule: Path
    trigger: TriggerSourceConfig | None = None


@dataclass(frozen=True)
class EdgeConfig:
    """Multi-instance edge configuration (ADR-013)."""

    application_version: str
    instances: tuple[InstanceConfig, ...]


def load_edge_config(path: Path) -> EdgeConfig:
    """Load and validate a multi-instance edge configuration YAML file.

    The document carries ``application_version`` and an ``instances:`` list;
    each instance embeds a full pipeline (models, detector settings, ROI) and
    its own rule path, so every instance is an independent inspection line
    (ADR-013). The legacy flat single-config form is unchanged.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot load edge configuration: {path}: {exc}") from exc
    doc = _require_mapping(raw, "edge configuration")
    _reject_unknown(doc, {"application_version", "instances"}, "edge configuration")
    application_version = doc.get("application_version", "0.1.0")
    if not isinstance(application_version, str) or not application_version:
        raise ConfigError("application_version must be a non-empty string")
    instances_raw = doc.get("instances")
    if not isinstance(instances_raw, list) or not instances_raw:
        raise ConfigError("instances must be a non-empty list")
    base = path.parent
    instances: list[InstanceConfig] = []
    seen: set[str] = set()
    for index, instance_raw in enumerate(instances_raw):
        name = f"instances[{index}]"
        instance = _require_mapping(instance_raw, name)
        _reject_unknown(
            instance,
            {
                "instance_id",
                "device_id",
                "camera",
                "inspection",
                "temporal",
                "rule",
                "models",
                "product_detection",
                "component_detection",
                "roi",
                "trigger",
            },
            name,
        )
        instance_id = _require_str(instance.get("instance_id"), f"{name}.instance_id")
        if instance_id in seen:
            raise ConfigError(f"duplicate instance_id {instance_id!r}")
        seen.add(instance_id)
        device_id_raw = instance.get("device_id")
        device_id: str | None = None
        if device_id_raw is not None:
            try:
                UUID(_require_str(device_id_raw, f"{name}.device_id"))
            except ValueError as exc:
                raise ConfigError(f"{name}.device_id must be a valid UUID") from exc
            device_id = device_id_raw
        camera = _parse_camera_source(
            _require_mapping(instance.get("camera"), f"{name}.camera"), base, f"{name}.camera"
        )
        inspection_raw = _require_mapping(instance.get("inspection") or {}, f"{name}.inspection")
        _reject_unknown(inspection_raw, {"enabled"}, f"{name}.inspection")
        inspection = InspectionRunConfig(
            enabled=_as_bool(inspection_raw.get("enabled"), f"{name}.inspection.enabled", False)
        )
        rule = _resolve_path(base, instance.get("rule"), f"{name}.rule")
        pipeline_doc = {
            "application_version": application_version,
            "models": instance.get("models"),
            "product_detection": instance.get("product_detection"),
            "component_detection": instance.get("component_detection"),
            "roi": instance.get("roi"),
        }
        pipeline_config = _parse_pipeline_doc(pipeline_doc, base)
        temporal = _parse_temporal(instance.get("temporal"), f"{name}.temporal")
        _validate_temporal_against_pipeline(temporal, pipeline_config, f"{name}.temporal")
        _validate_temporal_inspection_strategy(inspection, temporal, name)
        trigger = _parse_trigger_source(instance.get("trigger"), f"{name}.trigger")
        instances.append(
            InstanceConfig(
                instance_id=instance_id,
                device_id=device_id,
                camera=camera,
                inspection=inspection,
                temporal=temporal,
                pipeline=pipeline_config,
                rule=rule,
                trigger=trigger,
            )
        )
    return EdgeConfig(application_version=application_version, instances=tuple(instances))


def _parse_trigger_source(raw: Any, name: str) -> TriggerSourceConfig | None:
    """Parse an instance trigger/identity source (E4b).

    Only the deterministic ``mock`` source is supported until hardware
    trigger/barcode sources land (E6); anything else is a configuration error
    so a mock can never be mistaken for production hardware.
    """
    if raw is None:
        return None
    mapping = _require_mapping(raw, name)
    _reject_unknown(mapping, {"source", "products"}, name)
    source = mapping.get("source", "mock")
    if source != "mock":
        raise ConfigError(
            f"{name}.source {source!r} is not supported; only 'mock' is available (E4b)"
        )
    products_raw = mapping.get("products")
    if not isinstance(products_raw, list) or not products_raw:
        raise ConfigError(f"{name}.products must be a non-empty list")
    products: list[MockProductSpec] = []
    for index, product_raw in enumerate(products_raw):
        product_name = f"{name}.products[{index}]"
        product = _require_mapping(product_raw, product_name)
        _reject_unknown(product, {"identity", "barcode", "frames"}, product_name)
        frames = product.get("frames", 5)
        if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
            raise ConfigError(f"{product_name}.frames must be a positive integer")
        barcode = _require_optional_str(product.get("barcode"), f"{product_name}.barcode")
        products.append(
            MockProductSpec(
                identity=_require_str(product.get("identity"), f"{product_name}.identity"),
                frames=frames,
                barcode=barcode,
            )
        )
    return TriggerSourceConfig(source="mock", products=tuple(products))


def _parse_camera_source(raw: dict[str, Any], base: Path, name: str) -> CameraSourceConfig:
    """Parse and validate one camera source mapping (design 07.7)."""
    _reject_unknown(
        raw,
        {
            "source",
            "path",
            "url",
            "device",
            "fps",
            "loop",
            "reconnect",
        },
        name,
    )
    source = _require_str(raw.get("source"), f"{name}.source")
    if source not in _SOURCE_TYPES:
        raise ConfigError(f"{name}.source {source!r} is not one of {sorted(_SOURCE_TYPES)}")
    path: Path | None = None
    if "path" in raw and raw["path"] is not None:
        path = _resolve_path(base, raw["path"], f"{name}.path")
    url = _require_optional_str(raw.get("url"), f"{name}.url")
    device: int | str | None = None
    if "device" in raw and raw["device"] is not None:
        device_raw = raw["device"]
        if isinstance(device_raw, bool) or not isinstance(device_raw, (int, str)):
            raise ConfigError(f"{name}.device must be an integer or a device path string")
        device = device_raw
    if source in ("folder", "video") and path is None:
        raise ConfigError(f"{name}: source {source!r} requires a path")
    if source == "opencv-device" and device is None:
        raise ConfigError(f"{name}: source {source!r} requires a device")
    if source in ("rtsp", "http-image") and url is None:
        raise ConfigError(f"{name}: source {source!r} requires a url")
    if (
        url is not None
        and source == "rtsp"
        and not (url.startswith("rtsp://") or url.startswith("rtsps://"))
    ):
        raise ConfigError(f"{name}.url must be an rtsp:// url for source 'rtsp'")
    if (
        url is not None
        and source == "http-image"
        and not (url.startswith("http://") or url.startswith("https://"))
    ):
        raise ConfigError(f"{name}.url must be an http(s):// url for source 'http-image'")
    fps = raw.get("fps")
    if fps is not None:
        fps = _as_number(fps, f"{name}.fps")
        if fps <= 0:
            raise ConfigError(f"{name}.fps must be positive")
    reconnect_raw = raw.get("reconnect")
    reconnect_initial = 250
    reconnect_maximum = 10000
    if reconnect_raw is not None:
        reconnect = _require_mapping(reconnect_raw, f"{name}.reconnect")
        _reject_unknown(reconnect, {"initial_delay_ms", "maximum_delay_ms"}, f"{name}.reconnect")
        reconnect_initial = _as_positive_int(
            reconnect.get("initial_delay_ms"), f"{name}.reconnect.initial_delay_ms", 250
        )
        reconnect_maximum = _as_positive_int(
            reconnect.get("maximum_delay_ms"), f"{name}.reconnect.maximum_delay_ms", 10000
        )
        if reconnect_maximum < reconnect_initial:
            raise ConfigError(
                f"{name}.reconnect.maximum_delay_ms ({reconnect_maximum}) must be >= "
                f"initial_delay_ms ({reconnect_initial})"
            )
    return CameraSourceConfig(
        source=source,  # type: ignore[arg-type]
        path=path,
        url=url,
        device=device,
        fps=fps,
        loop=_as_bool(raw.get("loop"), f"{name}.loop", False),
        reconnect_initial_delay_ms=reconnect_initial,
        reconnect_maximum_delay_ms=reconnect_maximum,
    )


def _parse_temporal(raw: Any, name: str) -> TemporalAggregationConfig | None:
    """Parse and validate one instance ``temporal:`` block (design 10.7)."""
    if raw is None:
        return None
    doc = _require_mapping(raw, name)
    _reject_unknown(
        doc,
        {
            "minimum_valid_frames",
            "maximum_window_ms",
            "reject_duplicate_frame_ids",
            "window_strategy",
            "components",
        },
        name,
    )
    minimum_valid_frames = _as_positive_int(
        doc.get("minimum_valid_frames"), f"{name}.minimum_valid_frames", 1
    )
    maximum_window_ms = _as_positive_int(
        doc.get("maximum_window_ms"), f"{name}.maximum_window_ms", 2500
    )
    reject_duplicate = _as_bool(
        doc.get("reject_duplicate_frame_ids"), f"{name}.reject_duplicate_frame_ids", True
    )
    window_strategy_raw = doc.get("window_strategy", "time")
    if window_strategy_raw not in ("time", "identity"):
        raise ConfigError(f"{name}.window_strategy must be one of {sorted(('time', 'identity'))}")
    window_strategy: Literal["time", "identity"] = window_strategy_raw
    components: dict[str, ComponentTemporalPolicy] = {}
    comps_raw = doc.get("components")
    if comps_raw is not None:
        comps = _require_mapping(comps_raw, f"{name}.components")
        for code, policy_raw in comps.items():
            if not isinstance(code, str) or not code:
                raise ConfigError(f"{name}.components keys must be non-empty strings")
            pname = f"{name}.components.{code}"
            pmap = _require_mapping(policy_raw, pname)
            _reject_unknown(
                pmap,
                {
                    "high_confidence",
                    "medium_confidence",
                    "medium_hits",
                    "require_adjacent_hits",
                    "max_frame_gap",
                },
                pname,
            )
            high = _as_threshold(pmap.get("high_confidence"), f"{pname}.high_confidence", 0.9)
            medium = _as_threshold(pmap.get("medium_confidence"), f"{pname}.medium_confidence", 0.7)
            # Strict ordering is required by design 10.7; equality would
            # collapse the high-hit and repeated-medium evidence paths.
            if medium >= high:
                raise ConfigError(
                    f"{pname}: medium_confidence ({medium}) must be strictly less than "
                    f"high_confidence ({high})"
                )
            hits = _as_positive_int(pmap.get("medium_hits"), f"{pname}.medium_hits", 2)
            require_adjacent = _as_bool(
                pmap.get("require_adjacent_hits"), f"{pname}.require_adjacent_hits", True
            )
            gap = _as_non_negative_int(pmap.get("max_frame_gap"), f"{pname}.max_frame_gap", 1)
            components[code] = ComponentTemporalPolicy(
                high_confidence=high,
                medium_confidence=medium,
                medium_hits=hits,
                require_adjacent_hits=require_adjacent,
                max_frame_gap=gap,
            )
    return TemporalAggregationConfig(
        minimum_valid_frames=minimum_valid_frames,
        maximum_window_ms=maximum_window_ms,
        reject_duplicate_frame_ids=reject_duplicate,
        window_strategy=window_strategy,
        components=components,
    )


def _validate_temporal_against_pipeline(
    temporal: TemporalAggregationConfig | None, pipeline: PipelineConfig, name: str
) -> None:
    """Enforce observation_threshold <= medium_confidence < high_confidence (design 10.7)."""
    if temporal is None:
        return
    for code, policy in temporal.components.items():
        observation = pipeline.components.get(code)
        if observation is not None and observation.observation_threshold > policy.medium_confidence:
            raise ConfigError(
                f"{name}.components.{code}: medium_confidence ({policy.medium_confidence}) must be "
                f">= observation_threshold ({observation.observation_threshold})"
            )


def _validate_temporal_inspection_strategy(
    inspection: InspectionRunConfig,
    temporal: TemporalAggregationConfig | None,
    name: str,
) -> None:
    """Reject time-only temporal grouping before production inspection starts.

    ``window_strategy: time`` cannot prove physical-product isolation and is
    retained only for disabled/local development configuration. Any enabled
    temporal inspection must require validated identity correlation (PR-015
    production-boundary TODO).
    """
    if inspection.enabled and temporal is not None and temporal.window_strategy != "identity":
        raise ConfigError(
            f"{name}.temporal.window_strategy must be 'identity' when "
            "inspection.enabled is true; time-only windowing is development-only"
        )


def validate_temporal_against_rule(
    temporal: TemporalAggregationConfig | None, rule: RuleDefinition, name: str
) -> None:
    """Require exactly one temporal policy per rule-required component (PR-015 F6).

    Enabled temporal inspection must be fail-closed: a required component with
    no validated, versioned policy can never be released as OK. Policies for
    components the active rule does not require are configuration errors.
    """
    if temporal is None:
        return
    required = set(rule.required_components)
    configured = set(temporal.components)
    missing = sorted(required - configured)
    if missing:
        raise ConfigError(
            f"{name}: temporal policies missing for rule-required components: " + ", ".join(missing)
        )
    extra = sorted(configured - required)
    if extra:
        raise ConfigError(
            f"{name}: temporal policies for components the rule does not require: "
            + ", ".join(extra)
        )


def _as_non_negative_int(raw: Any, name: str, default: int) -> int:
    value = raw if raw is not None else default
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{name} must be a non-negative integer")
    return value


def _require_optional_str(raw: Any, name: str) -> str | None:
    if raw is None:
        return None
    return _require_str(raw, name)
