"""Aggregate configuration validation with an environment dimension.

Reuses the runtime fail-closed loaders from :mod:`assemblyvision_edge.config`
as the single source of truth, but collects every cross-file issue into one
report instead of failing on the first error, and adds dev/production boundary
checks that mirror the runtime rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from assemblyvision_domain.errors import ConfigError
from assemblyvision_vision.manifests import load_model_manifest

from assemblyvision_edge.config import (
    EdgeConfig,
    InstanceConfig,
    load_edge_config,
    load_pipeline_config,
    load_rule_definition,
    validate_model_version_declaration,
    validate_rule_component_compatibility,
    validate_temporal_against_rule,
)

from .i18n import Lang, t
from .schema import DEV_ONLY_EDGE

Env = Literal["dev", "production"]

Level = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class ValidationIssue:
    """One aggregate validation finding."""

    level: Level
    message: str
    path: str = ""


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot load {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a mapping document")
    return raw


def _instance_pipeline_doc(instance_raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "application_version": instance_raw.get("application_version", "0.1.0"),
        "models": instance_raw.get("models"),
        "product_detection": instance_raw.get("product_detection"),
        "component_detection": instance_raw.get("component_detection"),
        "roi": instance_raw.get("roi"),
        "identity": instance_raw.get("identity"),
    }


def _manifest_placeholder(manifest: Any) -> bool:
    """True when the manifest references placeholder (zeroed) artifacts."""
    for artifact in getattr(manifest, "artifacts", []) or []:
        if not artifact.sha256 or set(str(artifact.sha256)) == {"0"} or artifact.size_bytes == 0:
            return True
    return False


def validate_edge(
    pipeline_path: Path,
    rule_path: Path | None,
    env: Env,
    lang: Lang,
) -> list[ValidationIssue]:
    """Validate an edge pipeline (flat or multi-instance) plus its rule/manifests."""
    issues: list[ValidationIssue] = []
    raw: dict[str, Any] | None = None
    try:
        raw = _load_yaml(pipeline_path)
    except ConfigError as exc:
        issues.append(ValidationIssue("error", str(exc), str(pipeline_path)))
        return issues

    is_multi = "instances" in raw
    try:
        if is_multi:
            loaded: EdgeConfig | None = load_edge_config(pipeline_path)
        else:
            load_pipeline_config(pipeline_path)
            loaded = None
    except ConfigError as exc:
        issues.append(ValidationIssue("error", str(exc), str(pipeline_path)))
        return issues

    # Environment-boundary checks over the raw document.
    issues.extend(_check_env_boundaries(raw, env, lang, is_multi))

    if is_multi:
        if loaded is None:  # pragma: no cover - load_edge_config always returns an EdgeConfig
            return issues
        for instance in loaded.instances:
            issues.extend(_validate_instance(instance, env, lang))
        return issues

    # Flat form: the rule/manifests come from CLI arguments.
    if rule_path is None:
        issues.append(
            ValidationIssue(
                "error",
                t(lang, "Product / rule") + ": " + t(lang, "Config file does not exist"),
                str(pipeline_path),
            )
        )
        return issues
    try:
        pipeline = load_pipeline_config(pipeline_path)
        rule = load_rule_definition(rule_path)
        product_manifest = load_model_manifest(pipeline.product_manifest)
        component_manifest = load_model_manifest(pipeline.component_manifest)
    except ConfigError as exc:
        issues.append(ValidationIssue("error", str(exc), str(rule_path)))
        return issues
    issues.extend(
        _cross_checks(
            pipeline,
            product_manifest,
            component_manifest,
            rule,
            None,
            lang,
        )
    )
    if _manifest_placeholder(product_manifest) or _manifest_placeholder(component_manifest):
        issues.append(
            ValidationIssue(
                "error" if env == "production" else "warning",
                t(lang, "Model manifests") + ": placeholder",
                str(pipeline.product_manifest),
            )
        )
    return issues


def _validate_instance(instance: InstanceConfig, env: Env, lang: Lang) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        rule = load_rule_definition(instance.rule)
        product_manifest = load_model_manifest(instance.pipeline.product_manifest)
        component_manifest = load_model_manifest(instance.pipeline.component_manifest)
    except ConfigError as exc:
        issues.append(ValidationIssue("error", str(exc), f"instances[{instance.instance_id}]"))
        return issues
    issues.extend(
        _cross_checks(
            instance.pipeline,
            product_manifest,
            component_manifest,
            rule,
            instance,
            lang,
        )
    )
    if _manifest_placeholder(product_manifest) or _manifest_placeholder(component_manifest):
        issues.append(
            ValidationIssue(
                "error" if env == "production" else "warning",
                t(lang, "Model manifests") + ": placeholder",
                f"instances[{instance.instance_id}]",
            )
        )
    return issues


def _cross_checks(
    pipeline: Any,
    product_manifest: Any,
    component_manifest: Any,
    rule: Any,
    instance: InstanceConfig | None,
    lang: Lang,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for label, declared, manifest in (
        (
            "product_detection.model_version",
            pipeline.product_detection.model_version,
            product_manifest,
        ),
        (
            "component_detection.model_version",
            pipeline.component_detection.model_version,
            component_manifest,
        ),
    ):
        try:
            validate_model_version_declaration(declared, manifest, label)
        except ConfigError as exc:
            issues.append(ValidationIssue("error", str(exc), label))
    try:
        validate_rule_component_compatibility(rule, pipeline, component_manifest)
    except ConfigError as exc:
        issues.append(ValidationIssue("error", str(exc), "rule"))
    if instance is not None and instance.temporal is not None:
        try:
            validate_temporal_against_rule(
                instance.temporal, rule, f"instances[{instance.instance_id}]"
            )
        except ConfigError as exc:
            issues.append(ValidationIssue("error", str(exc), "temporal"))
    return issues


def _check_env_boundaries(
    raw: dict[str, Any], env: Env, lang: Lang, is_multi: bool
) -> list[ValidationIssue]:
    """Scan the raw document for dev-only markers and flag them per environment."""
    issues: list[ValidationIssue] = []
    if is_multi:
        instances_raw = raw.get("instances")
        if isinstance(instances_raw, list):
            for index, instance_raw in enumerate(instances_raw):
                if not isinstance(instance_raw, dict):
                    continue
                prefix = f"instances[{index}]"
                temporal = instance_raw.get("temporal")
                inspection = instance_raw.get("inspection") or {}
                window = temporal.get("window_strategy") if isinstance(temporal, dict) else None
                if window == "time" and inspection.get("enabled") is True:
                    # Runtime fail-closed rule (config.py): time-only windowing
                    # can never be enabled, in any environment.
                    issues.append(
                        ValidationIssue(
                            "error",
                            f"{prefix}.temporal.window_strategy 'time' cannot be "
                            "enabled; identity correlation is required",
                            f"{prefix}.temporal.window_strategy",
                        )
                    )
                trigger = instance_raw.get("trigger")
                if (
                    isinstance(trigger, dict)
                    and trigger.get("source") == "mock"
                    and env == "production"
                ):
                    issues.append(
                        ValidationIssue(
                            "error",
                            f"{prefix}.trigger.source 'mock' is development-only",
                            f"{prefix}.trigger.source",
                        )
                    )
    else:
        for key, marker in DEV_ONLY_EDGE:
            value = _dig(raw, key)
            if value == marker and env == "production":
                issues.append(
                    ValidationIssue(
                        "error",
                        f"{key} '{marker}' is development-only",
                        key,
                    )
                )
    return issues


def _dig(doc: dict[str, Any], dotted: str) -> Any:
    current: Any = doc
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


# -- central .env -------------------------------------------------------------

CENTRAL_ENV_REQUIRED = (
    "AV_CENTRAL_DATABASE_URL",
    "AV_CENTRAL_MINIO_ENDPOINT",
    "AV_CENTRAL_MINIO_ACCESS_KEY",
    "AV_CENTRAL_MINIO_SECRET_KEY",
    "AV_CENTRAL_MINIO_BUCKET",
)

_TOKEN_KEYS = ("AV_CENTRAL_ADMIN_TOKEN", "AV_CENTRAL_DEVICE_UPLOAD_TOKEN")
_MIN_TOKEN_LENGTH = 16


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into key/value pairs, preserving nothing else."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read env file {path}: {exc}") from exc
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def validate_central_env(path: Path, env: Env, lang: Lang) -> list[ValidationIssue]:
    """Validate a central .env file against the pilot schema and environment."""
    issues: list[ValidationIssue] = []
    try:
        values = parse_env_file(path)
    except ConfigError as exc:
        issues.append(ValidationIssue("error", str(exc), str(path)))
        return issues
    for key in CENTRAL_ENV_REQUIRED:
        if not values.get(key):
            issues.append(ValidationIssue("error", f"{key} is required", key))
    for key in _TOKEN_KEYS:
        value = values.get(key)
        if value is not None and value and len(value) < _MIN_TOKEN_LENGTH:
            issues.append(
                ValidationIssue("error", f"{key} must be at least {_MIN_TOKEN_LENGTH} chars", key)
            )
    if (
        values.get("AV_CENTRAL_SECURE_COOKIES", "").lower() in ("false", "no", "0")
        and env == "production"
    ):
        issues.append(
            ValidationIssue(
                "error",
                "AV_CENTRAL_SECURE_COOKIES=false is development-only",
                "AV_CENTRAL_SECURE_COOKIES",
            )
        )
    return issues


def validate_all(
    pipeline_path: Path | None,
    rule_path: Path | None,
    central_env_path: Path | None,
    env: Env,
    lang: Lang,
) -> list[ValidationIssue]:
    """Validate the requested configuration set and return every finding."""
    issues: list[ValidationIssue] = []
    if pipeline_path is not None:
        issues.extend(validate_edge(pipeline_path, rule_path, env, lang))
    if central_env_path is not None:
        issues.extend(validate_central_env(central_env_path, env, lang))
    return issues


def validate_edge_instance(
    pipeline_path: Path, instance_index: int | None, env: Env, lang: Lang
) -> list[ValidationIssue]:
    """Validate only one instance of a multi-instance pipeline.

    Used by the editor so a pre-existing issue in an unrelated instance does
    not block an edit to the selected instance.
    """
    if instance_index is None:
        return validate_edge(pipeline_path, None, env, lang)
    try:
        loaded = load_edge_config(pipeline_path)
    except ConfigError as exc:
        return [ValidationIssue("error", str(exc), str(pipeline_path))]
    instances = list(loaded.instances)
    if instance_index >= len(instances):
        return []
    return _validate_instance(instances[instance_index], env, lang)
