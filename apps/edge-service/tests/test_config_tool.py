"""Config tool tests: aggregate validation, dev/production boundary, backup, i18n."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import questionary
import yaml
from assemblyvision_edge.config_tool.backup import (
    create_backup,
    list_backups,
    restore_backup,
)
from assemblyvision_edge.config_tool.i18n import SUPPORTED_LANGS, t
from assemblyvision_edge.config_tool.validate import (
    parse_env_file,
    validate_central_env,
    validate_edge,
)

_MANIFEST = {
    "model_version_id": "00000000-0000-4000-8000-000000000002",
    "model_id": "00000000-0000-4000-8000-000000000022",
    "semantic_version": "1.0.0",
    "model_version_label": "component-yolo-1.0.0",
    "task": "COMPONENT_DETECTION",
    "runtime": "ultralytics",
    "input_width": 640,
    "input_height": 640,
    "class_names": ["component_a", "component_b", "manual"],
    "artifacts": [
        {
            "name": "weights",
            "uri": "../weights/component-yolo-1.0.0.pt",
            "sha256": "0" * 64,
            "size_bytes": 0,
        }
    ],
    "datasets": [],
    "split_strategy": "by_capture_session",
    "source_revision": "placeholder",
    "training_config_revision": "placeholder",
    "metrics": [],
    "limitations": ["placeholder"],
    "approved_by": None,
    "approved_at": None,
    "supersedes_model_version_id": None,
    "created_at": "2026-01-01T00:00:00Z",
}


def _rule_doc() -> dict[str, object]:
    return {
        "schema_version": 1,
        "rule_id": "model-a-presence",
        "rule_version": 3,
        "product_type": "model_a",
        "compatible_component_model_versions": ["component-yolo-1.0.0"],
        "barcode_required": False,
        "required_components": {
            "component_a": {"expected_count": 1},
            "component_b": {"expected_count": 1},
        },
        "mandatory_gates": {
            "product_detected": True,
            "roi_valid": True,
            "minimum_valid_frames_met": True,
        },
    }


def _flat_pipeline() -> dict[str, object]:
    return {
        "application_version": "0.1.0",
        "models": {
            "product_manifest": "product-manifest.json",
            "component_manifest": "component-manifest.json",
        },
        "product_detection": {
            "model_version": "product-yolo-1.0.0",
            "confidence_threshold": 0.7,
            "iou_threshold": 0.5,
        },
        "component_detection": {
            "model_version": "component-yolo-1.0.0",
            "iou_threshold": 0.5,
            "components": {
                "component_a": {"observation_threshold": 0.5},
                "component_b": {"observation_threshold": 0.5},
            },
        },
        "roi": {
            "margin_x_ratio": 0.05,
            "margin_y_ratio": 0.05,
            "min_area_pixels": 250000,
            "min_expanded_area_retained": 0.9,
            "normalize_perspective": False,
        },
    }


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    product_manifest = dict(_MANIFEST)
    product_manifest["model_version_label"] = "product-yolo-1.0.0"
    product_manifest["task"] = "PRODUCT_DETECTION"
    product_manifest["class_names"] = ["model_a"]
    (tmp_path / "product-manifest.json").write_text(json.dumps(product_manifest), encoding="utf-8")
    (tmp_path / "component-manifest.json").write_text(json.dumps(_MANIFEST), encoding="utf-8")
    (tmp_path / "product-rule.yaml").write_text(yaml.safe_dump(_rule_doc()), encoding="utf-8")
    return tmp_path


def test_validate_flat_dev_warns_placeholder(config_dir: Path) -> None:
    pipeline = config_dir / "pipeline.yaml"
    pipeline.write_text(yaml.safe_dump(_flat_pipeline()), encoding="utf-8")
    issues = validate_edge(pipeline, config_dir / "product-rule.yaml", "dev", "en")
    assert all(issue.level in ("error", "warning") for issue in issues)
    assert not [i for i in issues if i.level == "error"]
    assert any(i.level == "warning" for i in issues)


def test_validate_flat_production_rejects_placeholder(config_dir: Path) -> None:
    pipeline = config_dir / "pipeline.yaml"
    pipeline.write_text(yaml.safe_dump(_flat_pipeline()), encoding="utf-8")
    issues = validate_edge(pipeline, config_dir / "product-rule.yaml", "production", "en")
    assert any(i.level == "error" for i in issues)


def _multi_instance_doc(*, enabled: bool = False, window: str | None = None) -> dict[str, object]:
    instance: dict[str, object] = {
        "instance_id": "line-1",
        "camera": {"source": "video", "path": "/data/line.mp4", "fps": 25},
        "inspection": {"enabled": enabled},
        "models": {
            "product_manifest": "product-manifest.json",
            "component_manifest": "component-manifest.json",
        },
        "product_detection": {
            "model_version": "product-yolo-1.0.0",
            "confidence_threshold": 0.7,
            "iou_threshold": 0.5,
        },
        "component_detection": {
            "model_version": "component-yolo-1.0.0",
            "iou_threshold": 0.5,
            "components": {
                "component_a": {"observation_threshold": 0.5},
                "component_b": {"observation_threshold": 0.5},
            },
        },
        "roi": {
            "margin_x_ratio": 0.05,
            "margin_y_ratio": 0.05,
            "min_area_pixels": 250000,
            "min_expanded_area_retained": 0.9,
            "normalize_perspective": False,
        },
        "rule": "product-rule.yaml",
    }
    if window is not None:
        instance["temporal"] = {
            "window_strategy": window,
            "components": {
                "component_a": {
                    "high_confidence": 0.9,
                    "medium_confidence": 0.6,
                    "medium_hits": 2,
                    "require_adjacent_hits": True,
                    "max_frame_gap": 1,
                }
            },
        }
    return {"application_version": "0.1.0", "instances": [instance]}


def test_validate_multi_instance_production_rejects_time_window(config_dir: Path) -> None:
    pipeline = config_dir / "pipeline.cameras.yaml"
    pipeline.write_text(
        yaml.safe_dump(_multi_instance_doc(enabled=True, window="time")), encoding="utf-8"
    )
    issues = validate_edge(pipeline, None, "production", "en")
    assert any("window_strategy" in i.message for i in issues if i.level == "error")


def test_validate_multi_instance_placeholder_dev_warning_prod_error(config_dir: Path) -> None:
    pipeline = config_dir / "pipeline.cameras.yaml"
    pipeline.write_text(yaml.safe_dump(_multi_instance_doc()), encoding="utf-8")
    dev_issues = validate_edge(pipeline, None, "dev", "en")
    assert any(i.level == "warning" and "placeholder" in i.message for i in dev_issues)
    prod_issues = validate_edge(pipeline, None, "production", "en")
    assert any(i.level == "error" and "placeholder" in i.message for i in prod_issues)


def test_validate_central_env_required(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("AV_CENTRAL_SECURE_COOKIES=false\n", encoding="utf-8")
    issues = validate_central_env(env_path, "production", "en")
    errors = [i for i in issues if i.level == "error"]
    assert any("AV_CENTRAL_DATABASE_URL" in i.message for i in errors)
    assert any("secure" in i.message.lower() for i in errors)


def test_validate_central_env_production_rejects_insecure_cookies(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "AV_CENTRAL_DATABASE_URL=postgresql+psycopg://u:p@h/db\n"
        "AV_CENTRAL_MINIO_ENDPOINT=h:9000\n"
        "AV_CENTRAL_MINIO_ACCESS_KEY=k\n"
        "AV_CENTRAL_MINIO_SECRET_KEY=s\n"
        "AV_CENTRAL_MINIO_BUCKET=b\n"
        "AV_CENTRAL_SECURE_COOKIES=false\n",
        encoding="utf-8",
    )
    issues = validate_central_env(env_path, "production", "en")
    assert any(i.level == "error" and "SECURE_COOKIES" in i.message for i in issues)
    dev_issues = validate_central_env(env_path, "dev", "en")
    assert not any("SECURE_COOKIES" in i.message for i in dev_issues)


def test_parse_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        '# comment\nAV_CENTRAL_MINIO_SECURE=false\nAV_CENTRAL_ADMIN_TOKEN="quoted"\n',
        encoding="utf-8",
    )
    values = parse_env_file(env_path)
    assert values["AV_CENTRAL_MINIO_SECURE"] == "false"
    assert values["AV_CENTRAL_ADMIN_TOKEN"] == "quoted"  # noqa: S105 - test value
    assert "comment" not in values


def test_backup_list_restore_roundtrip(tmp_path: Path) -> None:
    config = tmp_path / "pipeline.yaml"
    config.write_text("application_version: 0.1.0\n", encoding="utf-8")
    backup = create_backup(config)
    assert backup.exists()

    config.write_text("application_version: 0.2.0\n", encoding="utf-8")
    entries = list_backups(config)
    assert len(entries) == 1
    assert entries[0].backup_path == backup

    restore_backup(config, backup)
    assert "0.1.0" in config.read_text(encoding="utf-8")


def test_backup_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        create_backup(tmp_path / "missing.yaml")


def test_validate_edge_instance_scopes_to_selected_instance(config_dir: Path) -> None:
    """Editing one instance is not blocked by a pre-existing issue elsewhere."""
    from assemblyvision_edge.config_tool.validate import validate_edge_instance

    pipeline = config_dir / "pipeline.cameras.yaml"
    # line-1 is complete; line-2 is missing component_b (pre-existing issue).
    doc: dict[str, Any] = _multi_instance_doc()
    instances: list[Any] = doc["instances"]
    instance_two = copy.deepcopy(instances[0])
    instance_two["instance_id"] = "line-2"
    del instance_two["component_detection"]["components"]["component_b"]
    doc["instances"] = [instances[0], instance_two]
    pipeline.write_text(yaml.safe_dump(doc), encoding="utf-8")

    # Whole-config validation reports the pre-existing issue...
    full = validate_edge(pipeline, None, "production", "en")
    assert any("component_b" in i.message for i in full if i.level == "error")
    # ...but the editor scopes to the selected instance (line-1 at index 0).
    scoped = validate_edge_instance(pipeline, 0, "production", "en")
    assert not any("component_b" in i.message for i in scoped)


def test_i18n_keys_present_in_all_languages() -> None:
    from assemblyvision_edge.config_tool.i18n import _MESSAGES

    for key, entries in _MESSAGES.items():
        for lang in SUPPORTED_LANGS:
            assert entries.get(lang), f"missing {lang} for key {key!r}"


def test_i18n_translate_fallback() -> None:
    assert t("en", "Quit") == "Quit"
    assert t("zh-CN", "Quit") == "退出"
    assert t("ja", "Quit") == "終了"
    # Unknown keys fall back to the key itself.
    assert t("en", "NOT_A_KEY") == "NOT_A_KEY"


def test_apply_change_writes_and_backs_up(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_apply_change validates, diffs, confirms, backs up, and writes."""
    from assemblyvision_edge.config_tool import edit as edit_module

    pipeline = config_dir / "pipeline.yaml"
    pipeline.write_text(yaml.safe_dump(_flat_pipeline()), encoding="utf-8")

    monkeypatch.setattr(questionary, "confirm", lambda msg, default=False: _FakeQ("y"))

    def _mutate(doc: dict[str, Any]) -> None:
        roi = doc.setdefault("roi", {})
        roi["min_area_pixels"] = 123456

    before = pipeline.read_text(encoding="utf-8")
    applied = edit_module._apply_change(
        pipeline,
        _mutate,
        lang="en",
        env="dev",
        validate=lambda doc, _result: [],
    )
    assert applied is True
    after = pipeline.read_text(encoding="utf-8")
    assert "123456" in after
    assert before != after
    backups = list_backups(pipeline)
    assert len(backups) == 1
    # The backup preserves the pre-change document.
    assert "250000" in backups[0].backup_path.read_text(encoding="utf-8")


def test_apply_change_skips_unchanged(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from assemblyvision_edge.config_tool import edit as edit_module

    pipeline = config_dir / "pipeline.yaml"
    pipeline.write_text(yaml.safe_dump(_flat_pipeline()), encoding="utf-8")

    applied = edit_module._apply_change(
        pipeline,
        lambda doc: None,
        lang="en",
        env="dev",
        validate=lambda doc, _result: [],
    )
    assert applied is False


def test_nested_field_paths_support_prefixes_and_lists() -> None:
    from assemblyvision_edge.config_tool.edit import _dig, _set

    document: dict[str, Any] = {
        "camera": {"fps": 25.0},
        "artifacts": [{"uri": "old.pt"}],
    }

    _set(document, "fps", 30.0, "camera")
    _set(document, "artifacts.0.uri", "new.pt")
    _set(document, "artifacts.0.size_bytes", 123)

    assert document["camera"] == {"fps": 30.0}
    assert document["artifacts"] == [{"uri": "new.pt", "size_bytes": 123}]
    assert _dig(document, "artifacts.0.uri") == "new.pt"


def test_prompt_manifest_path_selects_the_requested_manifest(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.config_tool.edit import _prompt_manifest_path

    pipeline = config_dir / "pipeline.yaml"
    pipeline.write_text(yaml.safe_dump(_flat_pipeline()), encoding="utf-8")
    monkeypatch.setattr(questionary, "select", lambda *args, **kwargs: _FakeQ("1: component"))

    assert _prompt_manifest_path(pipeline, "en") == config_dir / "component-manifest.json"


def test_missing_edit_paths_explain_required_options(capsys: pytest.CaptureFixture[str]) -> None:
    from assemblyvision_edge.config_tool.edit import _require_existing_file

    assert _require_existing_file(None, "--config", "Pipeline config file", "en") is None
    assert "Pipeline config file: Required option: --config PATH" in capsys.readouterr().out


def test_field_hint_shows_current_value_or_creating_new() -> None:
    from assemblyvision_edge.config_tool.edit import _field_hint

    assert _field_hint("en", "0.5") == "press enter to keep 0.5"
    assert _field_hint("en", "") == "creating new"
    assert _field_hint("zh-CN", "") == "正在新建"


def test_prompt_fields_lists_current_value_and_creating_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assemblyvision_edge.config_tool import edit as edit_module
    from assemblyvision_edge.config_tool.schema import DETECTION_SPEC

    prompts: list[str] = []

    class _TextQ:
        def __init__(self, prompt: str) -> None:
            prompts.append(prompt)

        def ask(self) -> str:
            return ""

    monkeypatch.setattr(questionary, "text", lambda prompt, default="": _TextQ(prompt))
    monkeypatch.setattr(questionary, "confirm", lambda *args, **kwargs: _FakeQ("y"))

    doc: dict[str, Any] = {"product_detection": {"confidence_threshold": 0.7}}
    edit_module._prompt_fields(doc, DETECTION_SPEC.fields, "en")

    joined = "\n".join(prompts)
    assert "press enter to keep 0.7" in joined
    assert "creating new" in joined


def test_edit_menu_ctrl_c_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    from assemblyvision_edge.config_tool import edit as edit_module

    calls: list[str] = []

    def _ctrl_c(message: str, **kwargs: object) -> str:
        calls.append(message)
        raise KeyboardInterrupt

    monkeypatch.setattr(questionary, "select", _ctrl_c)
    rc = edit_module._edit_loop(
        [t("en", "Product / rule"), t("en", "Quit")], "en", "dev", None, None, None
    )
    assert rc == 0
    assert len(calls) == 1


def test_edit_ctrl_c_during_object_edit_returns_to_menu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from assemblyvision_edge.config_tool import edit as edit_module

    rule = tmp_path / "product-rule.yaml"
    rule.write_text("rule_id: model-a\n", encoding="utf-8")
    answers = iter([t("en", "Product / rule"), t("en", "Quit")])

    def _select(message: str, **kwargs: object) -> _FakeQ:
        return _FakeQ(next(answers))

    def _raise_ctrl_c(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(questionary, "select", _select)
    monkeypatch.setattr(edit_module, "_edit_rule", _raise_ctrl_c)

    rc = edit_module._edit_loop(
        [t("en", "Product / rule"), t("en", "Quit")], "en", "dev", None, rule, None
    )
    assert rc == 0
    assert "Returned to the previous menu" in capsys.readouterr().out


class _FakeQ:
    """Minimal questionary stand-in returning canned answers."""

    def __init__(self, answer: str) -> None:
        self._answer = answer

    def ask(self) -> str:
        return self._answer
