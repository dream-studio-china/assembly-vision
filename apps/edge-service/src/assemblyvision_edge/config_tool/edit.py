"""Interactive configuration editing (questionary).

Edits the source YAML/JSON/env documents in place, guided by the object
schema. Every write is validated, diffed, confirmed, and snapshotted first
(backup) so a mistaken edit is reversible.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import questionary
import yaml

from .backup import create_backup
from .i18n import Lang, t
from .schema import (
    CAMERA_SOURCE_CHOICES,
    CAMERA_SOURCE_FIELDS,
    CENTRAL_ENV_FIELDS,
    DETECTION_SPEC,
    MANIFEST_FIELDS,
    ROI_SPEC,
    FieldSpec,
    parse_bool,
    parse_float,
    parse_int,
)
from .validate import (
    Env,
    ValidationIssue,
    validate_central_env,
    validate_edge,
    validate_edge_instance,
)


def _load_yaml_doc(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping document")
    return raw


def _write_yaml_doc(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _load_json_doc(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a JSON object")
    return raw


def _write_json_doc(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _env_lines(values: dict[str, str]) -> str:
    return "".join(f"{key}={value}\n" for key, value in values.items())


def _read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    path.write_text(_env_lines(values), encoding="utf-8")


def _diff_documents(old: dict[str, Any], new: dict[str, Any], prefix: str = "") -> list[str]:
    """Return a human-readable field-level diff (old -> new)."""

    def walk(a: Any, b: Any, path: str, out: list[str]) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                sub = f"{path}.{key}" if path else str(key)
                walk(a.get(key), b.get(key), sub, out)
            return
        if isinstance(a, list) and isinstance(b, list):
            if a != b:
                out.append(f"{path}: {a!r} -> {b!r}")
            return
        if a != b:
            out.append(f"{path}: {a!r} -> {b!r}")

    out: list[str] = []
    walk(old, new, prefix, out)
    return out


def _apply_change(
    path: Path,
    mutate: Callable[[dict[str, Any]], Any],
    lang: Lang,
    env: Env,
    validate: Callable[[dict[str, Any], Any], list[ValidationIssue]] | None = None,
) -> bool:
    """Validate + diff + confirm + backup + write one document change."""
    if path.name.endswith(".env"):
        original: dict[str, Any] = _read_env_values(path)
    else:
        original = _load_json_doc(path) if path.suffix == ".json" else _load_yaml_doc(path)
    mutated = copy.deepcopy(original)
    mutate_result = mutate(mutated)
    if mutated == original:
        print(t(lang, "No configuration changes made"))
        return False
    issues = validate(mutated, mutate_result) if validate is not None else []
    errors = [issue for issue in issues if issue.level == "error"]
    print(t(lang, "Change preview"))
    if isinstance(mutate_result, int) and "instances" in original and "instances" in mutated:
        # Multi-instance edit: diff only the edited instance, not the whole file.
        index = mutate_result
        if 0 <= index < len(original["instances"]) and 0 <= index < len(mutated["instances"]):
            for line in _diff_documents(
                original["instances"][index], mutated["instances"][index], f"instances[{index}]"
            ):
                print(f"  {line}")
        else:
            for line in _diff_documents(original, mutated):
                print(f"  {line}")
    else:
        for line in _diff_documents(original, mutated):
            print(f"  {line}")
    if errors:
        for issue in errors:
            print(f"  [error] {issue.path}: {issue.message}")
        print(t(lang, "Validation failed"))
        force = questionary.confirm(t(lang, "Apply anyway"), default=False).ask()
        if not force:
            print(t(lang, "Change cancelled"))
            return False
    confirmed = questionary.confirm(t(lang, "Apply changes"), default=True).ask()
    if not confirmed:
        print(t(lang, "Change cancelled"))
        return False
    backup = create_backup(path)
    if path.suffix == ".json":
        _write_json_doc(path, mutated)
    elif path.name.endswith(".env"):
        _write_env_file(path, mutated)
    else:
        _write_yaml_doc(path, mutated)
    print(f"{t(lang, 'Backed up')}: {backup.name}")
    print(f"{t(lang, 'Written')}: {path}")
    return True


# -- field prompts ------------------------------------------------------------


def _field_hint(lang: Lang, display: str) -> str:
    """Prompt hint: show the current value, or 'creating new' when unset."""
    if not display:
        return t(lang, "Creating new")
    return f"{t(lang, 'Press enter to keep')} {display}"


def _prompt_fields(
    doc: dict[str, Any],
    fields: tuple[FieldSpec, ...],
    lang: Lang,
    prefix: str = "",
    exclude: set[str] | None = None,
) -> None:
    """Ask each field, using the current value as the default."""
    excluded = exclude or set()
    for spec in fields:
        if spec.key in excluded:
            continue
        current = _dig(doc, f"{prefix}.{spec.key}" if prefix else spec.key)
        label = t(lang, spec.label_key)
        if spec.type == "bool":
            default = current if isinstance(current, bool) else False
            display = str(current).lower() if isinstance(current, bool) else ""
            value = questionary.confirm(
                f"{label} [{_field_hint(lang, display)}]", default=default
            ).ask()
            if value is None:
                continue
            _set(doc, spec.key, value, prefix)
            continue
        default_text = "" if current is None else str(current)
        if spec.type == "choice" and spec.choices:
            selected = default_text if default_text in spec.choices else None
            choice = questionary.select(
                f"{label} [{_field_hint(lang, default_text)}]",
                choices=list(spec.choices),
                default=selected,
            ).ask()
            if choice is not None:
                _set(doc, spec.key, choice, prefix)
            continue
        hint = _field_hint(lang, default_text)
        if spec.required and not default_text:
            hint = f"{hint}, {t(lang, 'Required')}"
        prompt = f"{label} [{hint}]: "
        raw = questionary.text(prompt, default=default_text).ask()
        # An empty answer keeps the current value (or skips an unset field).
        if raw is None or raw == "":
            continue
        try:
            _set(doc, spec.key, _coerce(spec, raw), prefix)
        except (TypeError, ValueError) as exc:
            print(f"  {t(lang, 'Invalid value')}: {spec.key}: {exc}")


def _coerce(spec: FieldSpec, raw: str) -> Any:
    if spec.type == "int":
        return parse_int(raw)
    if spec.type == "float":
        return parse_float(raw)
    if spec.type == "bool":
        return parse_bool(raw)
    return raw


def _dig(doc: dict[str, Any], dotted: str) -> Any:
    current: Any = doc
    for part in dotted.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _set(doc: dict[str, Any], key: str, value: Any, prefix: str = "") -> None:
    parts = f"{prefix}.{key}".strip(".").split(".")
    current: Any = doc
    for position, part in enumerate(parts[:-1]):
        next_part = parts[position + 1]
        if isinstance(current, dict):
            if part not in current:
                current[part] = [] if next_part.isdigit() else {}
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            while len(current) <= index:
                current.append([] if next_part.isdigit() else {})
            current = current[index]
        else:
            raise ValueError(f"cannot set nested field {'.'.join(parts)!r}")
    final_part = parts[-1]
    if isinstance(current, dict):
        current[final_part] = value
    elif isinstance(current, list) and final_part.isdigit():
        index = int(final_part)
        while len(current) <= index:
            current.append(None)
        current[index] = value
    else:
        raise ValueError(f"cannot set nested field {'.'.join(parts)!r}")


# -- object editors -----------------------------------------------------------


def _edit_rule(doc: dict[str, Any], lang: Lang) -> None:
    # rule identity fields
    rule_id = questionary.text(
        f"{t(lang, 'Rule id')} [{_field_hint(lang, str(doc.get('rule_id', '')))}]",
        default=str(doc.get("rule_id", "")),
    ).ask()
    if rule_id is not None and rule_id.strip():
        doc["rule_id"] = rule_id.strip()
    version_raw = questionary.text(
        f"{t(lang, 'Rule version')} [{_field_hint(lang, str(doc.get('rule_version', '')))}]",
        default=str(doc.get("rule_version", "")),
    ).ask()
    if version_raw is not None and version_raw.strip():
        doc["rule_version"] = parse_int(version_raw)
    product_type = questionary.text(
        f"{t(lang, 'Product type')} [{_field_hint(lang, str(doc.get('product_type', '')))}]",
        default=str(doc.get("product_type", "")),
    ).ask()
    if product_type is not None and product_type.strip():
        doc["product_type"] = product_type.strip()
    barcode = questionary.confirm(
        f"{t(lang, 'Barcode required')} [{_field_hint(lang, _bool_display(doc.get('barcode_required')))}]",
        default=bool(doc.get("barcode_required", False)),
    ).ask()
    if barcode is not None:
        doc["barcode_required"] = barcode
    compatible = questionary.text(
        f"{t(lang, 'Compatible component model versions')} "
        f"[{_field_hint(lang, ', '.join(doc.get('compatible_component_model_versions', []) or []))}]",
        default=", ".join(doc.get("compatible_component_model_versions", []) or []),
    ).ask()
    if compatible is not None and compatible.strip():
        doc["compatible_component_model_versions"] = [
            item.strip() for item in compatible.split(",") if item.strip()
        ]
    # required_components expected counts
    required = doc.setdefault("required_components", {})
    codes = sorted(required)
    print(t(lang, "Existing instances") + ": " + ", ".join(codes) if codes else "")
    for code in list(required):
        expected = (
            required[code].get("expected_count", 1) if isinstance(required[code], dict) else 1
        )
        raw = questionary.text(
            f"{code} {t(lang, 'Value')} [{_field_hint(lang, str(expected))}]: ",
            default=str(expected),
        ).ask()
        if raw is not None and raw.strip():
            required[code] = {"expected_count": parse_int(raw)}


def _bool_display(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else ""


def _select_instance_index(doc: dict[str, Any], lang: Lang) -> int | None:
    instances = doc.get("instances")
    if not isinstance(instances, list) or not instances:
        print(t(lang, "No instances configured"))
        return None
    choices = [
        f"{i}: {inst.get('instance_id', '?')} ({inst.get('camera', {}).get('source', '?')})"
        for i, inst in enumerate(instances)
        if isinstance(inst, dict)
    ]
    choice = questionary.select(t(lang, "Select an instance"), choices=choices).ask()
    if choice is None:
        return None
    return int(choice.split(":")[0])


def _edit_instances(doc: dict[str, Any], lang: Lang) -> None:
    if "instances" not in doc:
        print(t(lang, "Cannot edit a flat single-instance config; use the multi-instance form"))
        return
    instances = doc.setdefault("instances", [])
    while True:
        action = questionary.select(
            t(lang, "Select an action"),
            choices=[t(lang, "Add"), t(lang, "Edit"), t(lang, "Delete"), t(lang, "Back")],
        ).ask()
        if action in (None, t(lang, "Back")):
            return
        if action == t(lang, "Add"):
            instance: dict[str, Any] = {}
            instance_id = questionary.text(
                f"{t(lang, 'New instance id')} [{_field_hint(lang, '')}]"
            ).ask()
            if not instance_id or not instance_id.strip():
                continue
            instance["instance_id"] = instance_id.strip()
            source = questionary.select(
                f"{t(lang, 'Camera source')} [{_field_hint(lang, '')}]",
                choices=list(CAMERA_SOURCE_CHOICES),
            ).ask()
            if source is None:
                continue
            instance["camera"] = {"source": source}
            _prompt_fields(
                instance, CAMERA_SOURCE_FIELDS[source], lang, "camera", exclude={"source"}
            )
            instance["inspection"] = {"enabled": False}
            # Copy the pipeline sections (models/detection/roi) from the first
            # existing instance so a new camera starts from the site's current
            # configuration instead of an invalid empty skeleton.
            template = next((inst for inst in instances if isinstance(inst, dict)), None)
            for section in (
                "models",
                "product_detection",
                "component_detection",
                "roi",
                "rule",
                "identity",
                "temporal",
                "trigger",
            ):
                if template is not None and section in template:
                    instance[section] = copy.deepcopy(template[section])
            instances.append(instance)
            return
        if action == t(lang, "Edit"):
            index = _select_instance_index(doc, lang)
            if index is None:
                continue
            instance = instances[index]
            source = instance.get("camera", {}).get("source")
            if isinstance(source, str) and source in CAMERA_SOURCE_FIELDS:
                _prompt_fields(instance, CAMERA_SOURCE_FIELDS[source], lang, "camera")
            return
        if action == t(lang, "Delete"):
            index = _select_instance_index(doc, lang)
            if index is None:
                continue
            del instances[index]
            return


def _edit_thresholds(doc: dict[str, Any], lang: Lang) -> int | None:
    index: int | None = None
    if "instances" in doc:
        index = _select_instance_index(doc, lang)
        if index is None:
            return None
        instance = doc["instances"][index]
        _prompt_fields(instance, DETECTION_SPEC.fields, lang)
    else:
        _prompt_fields(doc, DETECTION_SPEC.fields, lang)
    return index


def _edit_roi(doc: dict[str, Any], lang: Lang) -> int | None:
    index: int | None = None
    if "instances" in doc:
        index = _select_instance_index(doc, lang)
        if index is None:
            return None
        instance = doc["instances"][index]
        roi = instance.setdefault("roi", {})
        _prompt_fields(roi, ROI_SPEC.fields, lang)
    else:
        roi = doc.setdefault("roi", {})
        _prompt_fields(roi, ROI_SPEC.fields, lang)
    return index


def _edit_identity(doc: dict[str, Any], lang: Lang) -> int | None:
    index: int | None = None
    if "instances" in doc:
        index = _select_instance_index(doc, lang)
        if index is None:
            return None
        identity = doc["instances"][index].setdefault("identity", {}).setdefault("barcode", {})
    else:
        identity = doc.setdefault("identity", {}).setdefault("barcode", {})
    enabled = questionary.confirm(
        f"{t(lang, 'Barcode identity enabled')} "
        f"[{_field_hint(lang, _bool_display(identity.get('enabled')))}]",
        default=bool(identity.get("enabled", False)),
    ).ask()
    if enabled is not None:
        identity["enabled"] = enabled
    required = questionary.confirm(
        f"{t(lang, 'Barcode identity required')} "
        f"[{_field_hint(lang, _bool_display(identity.get('required')))}]",
        default=bool(identity.get("required", False)),
    ).ask()
    if required is not None:
        identity["required"] = required
    mapping = questionary.text(
        f"{t(lang, 'Barcode mapping file')} "
        f"[{_field_hint(lang, str(identity.get('mapping_file', '')))}]",
        default=str(identity.get("mapping_file", "")),
    ).ask()
    if mapping is not None and mapping.strip():
        identity["mapping_file"] = mapping.strip()
    return index


def _edit_manifest(doc: dict[str, Any], lang: Lang) -> None:
    _prompt_fields(doc, MANIFEST_FIELDS, lang)


def _edit_central_env(doc: dict[str, str], lang: Lang) -> None:
    for spec in CENTRAL_ENV_FIELDS:
        label = t(lang, spec.label_key)
        current = doc.get(spec.key, "")
        if spec.type == "bool":
            default = current.lower() in ("true", "yes", "1") if current else False
            display = "true" if default else ("false" if current else "")
            value = questionary.confirm(
                f"{label} [{_field_hint(lang, display)}]", default=default
            ).ask()
            if value is not None:
                doc[spec.key] = "true" if value else "false"
            continue
        display = "*" * min(len(current), 8) if current else ""
        prompt = f"{label} [{_field_hint(lang, display)}]: "
        raw = questionary.text(prompt, default=current if current else "").ask()
        if raw is None or raw == "" and current:
            continue
        doc[spec.key] = raw


def _require_existing_file(
    path: Path | None, option: str, label_key: str, lang: Lang
) -> Path | None:
    """Return an existing input file or print the required CLI option."""
    if path is not None and path.exists():
        return path
    print(f"{t(lang, label_key)}: {t(lang, 'Required option')} {option} PATH")
    return None


def _pipeline_validator(
    pipeline_path: Path,
    rule_path: Path | None,
    env: Env,
    lang: Lang,
    *,
    scoped_instance: bool,
) -> Callable[[dict[str, Any], Any], list[ValidationIssue]]:
    """Create an in-memory pipeline validator for one interactive edit."""

    def validate(doc: dict[str, Any], result: Any) -> list[ValidationIssue]:
        instance_index = result if scoped_instance and isinstance(result, int) else None
        return _validate_doc(
            pipeline_path, doc, rule_path, env, lang, instance_index=instance_index
        )

    return validate


# -- top-level entry ----------------------------------------------------------


def run_edit(
    lang: Lang,
    env: Env,
    pipeline_path: Path | None,
    rule_path: Path | None,
    central_env_path: Path | None,
) -> int:
    """Interactive object-menu loop."""
    menu_choices = [
        t(lang, "Product / rule"),
        t(lang, "Camera instances (devices)"),
        t(lang, "Detection thresholds"),
        t(lang, "ROI"),
        t(lang, "Identity / barcode"),
        t(lang, "Model manifests"),
        t(lang, "Central server (.env)"),
        t(lang, "Quit"),
    ]
    try:
        return _edit_loop(menu_choices, lang, env, pipeline_path, rule_path, central_env_path)
    except Exception:  # noqa: BLE001 - interactive prompts need a terminal
        print(
            f"{t(lang, 'Error')}: interactive editing requires a terminal; "
            "use 'config validate' for non-interactive checks"
        )
        return 2


def _edit_loop(
    menu_choices: list[str],
    lang: Lang,
    env: Env,
    pipeline_path: Path | None,
    rule_path: Path | None,
    central_env_path: Path | None,
) -> int:
    while True:
        try:
            choice = questionary.select(
                t(lang, "Select an object to edit"), choices=menu_choices
            ).ask()
        except KeyboardInterrupt:
            # Ctrl+C on the object menu exits the tool cleanly.
            print()
            return 0
        if choice in (None, t(lang, "Quit")):
            return 0
        try:
            _dispatch_choice(choice, lang, env, pipeline_path, rule_path, central_env_path)
        except KeyboardInterrupt:
            # Ctrl+C inside an object edit returns to the object menu.
            print(t(lang, "Returned to the previous menu"))
    return 0


def _dispatch_choice(
    choice: str,
    lang: Lang,
    env: Env,
    pipeline_path: Path | None,
    rule_path: Path | None,
    central_env_path: Path | None,
) -> None:
    if choice == t(lang, "Product / rule"):
        rule = _require_existing_file(rule_path, "--rule", "Product / rule", lang)
        if rule is None:
            return
        _apply_change(rule, lambda doc: _edit_rule(doc, lang), lang, env)
    elif choice == t(lang, "Camera instances (devices)"):
        pipeline = _require_existing_file(pipeline_path, "--config", "Pipeline config file", lang)
        if pipeline is None:
            return
        pipeline_file = pipeline
        _apply_change(
            pipeline_file,
            lambda doc: _edit_instances(doc, lang),
            lang,
            env,
            validate=_pipeline_validator(
                pipeline_file, rule_path, env, lang, scoped_instance=False
            ),
        )
    elif choice == t(lang, "Detection thresholds"):
        pipeline = _require_existing_file(pipeline_path, "--config", "Pipeline config file", lang)
        if pipeline is None:
            return
        pipeline_file = pipeline

        _apply_change(
            pipeline_file,
            lambda doc: _edit_thresholds(doc, lang),
            lang,
            env,
            validate=_pipeline_validator(pipeline_file, rule_path, env, lang, scoped_instance=True),
        )
    elif choice == t(lang, "ROI"):
        pipeline = _require_existing_file(pipeline_path, "--config", "Pipeline config file", lang)
        if pipeline is None:
            return
        pipeline_file = pipeline

        _apply_change(
            pipeline_file,
            lambda doc: _edit_roi(doc, lang),
            lang,
            env,
            validate=_pipeline_validator(pipeline_file, rule_path, env, lang, scoped_instance=True),
        )
    elif choice == t(lang, "Identity / barcode"):
        pipeline = _require_existing_file(pipeline_path, "--config", "Pipeline config file", lang)
        if pipeline is None:
            return
        pipeline_file = pipeline

        _apply_change(
            pipeline_file,
            lambda doc: _edit_identity(doc, lang),
            lang,
            env,
            validate=_pipeline_validator(pipeline_file, rule_path, env, lang, scoped_instance=True),
        )
    elif choice == t(lang, "Model manifests"):
        pipeline = _require_existing_file(pipeline_path, "--config", "Pipeline config file", lang)
        if pipeline is None:
            return
        manifest_path = _prompt_manifest_path(pipeline, lang)
        if manifest_path is None:
            return
        _apply_change(
            manifest_path,
            lambda doc: _edit_manifest(doc, lang),
            lang,
            env,
            validate=lambda doc, _result: _validate_manifest(doc, lang),
        )
    elif choice == t(lang, "Central server (.env)"):
        central_env = _require_existing_file(
            central_env_path, "--central", "Central env file", lang
        )
        if central_env is None:
            return
        _apply_change(
            central_env,
            lambda doc: _edit_central_env(doc, lang),
            lang,
            env,
            validate=lambda doc, _result: _validate_env(doc, env, lang),
        )


def _prompt_manifest_path(pipeline_path: Path, lang: Lang) -> Path | None:
    try:
        doc = _load_yaml_doc(pipeline_path)
    except (OSError, ValueError) as exc:
        print(f"  {exc}")
        return None
    models = doc.get("models")
    if not isinstance(models, dict):
        instance_index = _select_instance_index(doc, lang)
        if instance_index is None:
            return None
        instances = doc.get("instances")
        if not isinstance(instances, list) or not isinstance(instances[instance_index], dict):
            return None
        models = instances[instance_index].get("models")
    candidates: list[tuple[str, Path]] = []
    if isinstance(models, dict):
        for label_key, path_key in (
            ("product manifest", "product_manifest"),
            ("component manifest", "component_manifest"),
        ):
            raw = models.get(path_key)
            if isinstance(raw, str) and raw:
                candidates.append((t(lang, label_key), (pipeline_path.parent / raw).resolve()))
    if not candidates:
        print(t(lang, "Model manifests") + ": " + t(lang, "Not found"))
        return None
    choice = questionary.select(
        t(lang, "Select a manifest"),
        choices=[f"{index}: {label}: {path}" for index, (label, path) in enumerate(candidates)],
    ).ask()
    if choice is None:
        return None
    try:
        index = int(choice.split(":", 1)[0])
    except ValueError:
        return None
    return candidates[index][1] if 0 <= index < len(candidates) else None


def _validate_doc(
    pipeline_path: Path,
    doc: dict[str, Any],
    rule_path: Path | None,
    env: Env,
    lang: Lang,
    instance_index: int | None = None,
) -> list[ValidationIssue]:
    """Validate the in-memory pipeline document by round-tripping it to disk.

    The temporary file is written next to the real pipeline so relative
    rule/manifest paths (e.g. ``../../models/manifests/...``) resolve exactly
    as they do at runtime. When ``instance_index`` is set (multi-instance
    edit), only that instance is validated so a pre-existing issue in an
    unrelated instance does not block the edit.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w",
        dir=str(pipeline_path.parent),
        prefix=".config-tool-",
        suffix=".yaml",
        delete=False,
        encoding="utf-8",
    ) as handle:
        temp_path = Path(handle.name)
        yaml.safe_dump(doc, handle, sort_keys=False, allow_unicode=True)
    try:
        if instance_index is None:
            return validate_edge(temp_path, rule_path, env, lang)
        return validate_edge_instance(temp_path, instance_index, env, lang)
    finally:
        temp_path.unlink(missing_ok=True)


def _validate_manifest(doc: dict[str, Any], lang: Lang) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    sha = doc.get("artifacts", [{}])[0].get("sha256", "") if doc.get("artifacts") else ""
    if not sha or set(str(sha)) == {"0"}:
        issues.append(
            ValidationIssue(
                "warning", t(lang, "Model manifests") + ": placeholder", "artifacts.0.sha256"
            )
        )
    return issues


def _validate_env(doc: dict[str, str], env: Env, lang: Lang) -> list[ValidationIssue]:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as handle:
        temp_path = Path(handle.name)
        handle.write(_env_lines(doc))
    try:
        return validate_central_env(temp_path, env, lang)
    finally:
        temp_path.unlink(missing_ok=True)
