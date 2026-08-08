"""Tests for the edge runtime state (EdgeRuntime) incl. sad paths."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from assemblyvision_domain.errors import ConfigError
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime, _build_pipeline

RULE_ID = "model-a-presence"


def _fake_manifest() -> SimpleNamespace:
    return SimpleNamespace(model_version_id=uuid4())


def _fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        application_version="0.1.0",
        product_detection=SimpleNamespace(
            model_version="product-yolo-1.0.0",
            confidence_threshold=0.7,
            iou_threshold=0.5,
        ),
        component_detection=SimpleNamespace(
            model_version="component-yolo-1.0.0",
            iou_threshold=0.5,
        ),
        components={
            "component_a": SimpleNamespace(observation_threshold=0.5),
            "component_b": SimpleNamespace(observation_threshold=0.5),
        },
        roi=SimpleNamespace(
            margin_x_ratio=0.05,
            margin_y_ratio=0.05,
            min_area_pixels=250000,
            min_expanded_area_retained=0.9,
            normalize_perspective=False,
        ),
    )


def _fake_rule() -> SimpleNamespace:
    return SimpleNamespace(
        rule_id=RULE_ID,
        rule_version=3,
        product_type="model_a",
        required_components={"component_a": {}, "component_b": {}},
        model_dump=lambda mode="json": {
            "rule_id": RULE_ID,
            "rule_version": 3,
            "product_type": "model_a",
            "required_components": {"component_a": {}, "component_b": {}},
        },
    )


def _fake_pipeline() -> SimpleNamespace:
    return SimpleNamespace(
        _product_manifest=_fake_manifest(),
        _component_manifest=_fake_manifest(),
        _config=_fake_config(),
        _rule=_fake_rule(),
    )


def _settings(tmp_path: Path, **overrides: object) -> ServerSettings:
    (tmp_path / "out").mkdir(exist_ok=True)
    return ServerSettings(
        output_root=tmp_path / "out",
        db_path=tmp_path / "edge.sqlite3",
        **overrides,  # type: ignore[arg-type]
    )


def test_resolve_device_id_from_settings(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path, device_id=str(uuid4())))
    assert isinstance(runtime.device_id, UUID)
    assert str(runtime.device_id) == _settings(tmp_path, device_id=str(runtime.device_id)).device_id


def test_resolve_device_id_generates_when_absent(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    assert isinstance(runtime.device_id, UUID)


def test_load_pipeline_without_config_sets_error(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    runtime.load_pipeline()
    assert runtime.pipeline is None
    assert "not configured" in (runtime.pipeline_error or "")


def test_load_pipeline_failure_is_non_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "assemblyvision_edge.api.state._build_pipeline",
        lambda settings, rule_registry=None: (_ for _ in ()).throw(ConfigError("boom")),
    )
    settings = _settings(
        tmp_path, config_path=tmp_path / "pipeline.yaml", rule_path=tmp_path / "rule.yaml"
    )
    runtime = EdgeRuntime(settings)
    runtime.load_pipeline()
    assert runtime.pipeline is None
    assert "boom" in (runtime.pipeline_error or "")
    assert runtime.pipeline_error_code == "CONFIG_INVALID"


def test_load_pipeline_value_error_maps_to_config_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "assemblyvision_edge.api.state._build_pipeline",
        lambda settings, rule_registry=None: (_ for _ in ()).throw(ValueError("bad uuid")),
    )
    settings = _settings(
        tmp_path, config_path=tmp_path / "pipeline.yaml", rule_path=tmp_path / "rule.yaml"
    )
    runtime = EdgeRuntime(settings)
    runtime.load_pipeline()
    assert runtime.pipeline is None
    assert runtime.pipeline_error_code == "CONFIG_INVALID"


def test_load_pipeline_passes_durable_rule_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.persistence.repository import EdgeRepository

    captured: list[object] = []

    def fake_build(settings: object, rule_registry: object | None = None) -> object:
        captured.append(rule_registry)
        return _fake_pipeline()

    monkeypatch.setattr("assemblyvision_edge.api.state._build_pipeline", fake_build)
    settings = _settings(
        tmp_path, config_path=tmp_path / "pipeline.yaml", rule_path=tmp_path / "rule.yaml"
    )
    runtime = EdgeRuntime(settings)
    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        runtime.load_pipeline(repository)
    finally:
        repository.close()
    assert captured and captured[0] is not None

    captured.clear()
    runtime2 = EdgeRuntime(settings)
    runtime2.load_pipeline()
    assert captured == [None]


def test_load_pipeline_maps_durable_rule_conflict_to_config_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.persistence.repository import EdgeRepository, RepositoryError

    def conflicting_build(settings: object, rule_registry: object | None = None) -> object:
        raise RepositoryError(
            "rule identity model-a-presence v3 was previously registered with different content"
        )

    monkeypatch.setattr("assemblyvision_edge.api.state._build_pipeline", conflicting_build)
    settings = _settings(
        tmp_path, config_path=tmp_path / "pipeline.yaml", rule_path=tmp_path / "rule.yaml"
    )
    runtime = EdgeRuntime(settings)
    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        runtime.load_pipeline(repository)
    finally:
        repository.close()
    assert runtime.pipeline is None
    assert runtime.pipeline_error_code == "CONFIG_INVALID"
    assert "different content" in (runtime.pipeline_error or "")


def test_device_status_exposes_stable_config_invalid_reason(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    runtime.pipeline_error = "rule requires components missing from configuration: ghost"
    runtime.pipeline_error_code = "CONFIG_INVALID"
    status = runtime.device_status(0)
    assert status["inspection_ready"] is False
    assert status["inspection_error_code"] == "CONFIG_INVALID"
    assert "ghost" not in status["inspection_error_code"]


def test_load_pipeline_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "assemblyvision_edge.api.state._build_pipeline",
        lambda settings, rule_registry=None: _fake_pipeline(),
    )
    settings = _settings(
        tmp_path, config_path=tmp_path / "pipeline.yaml", rule_path=tmp_path / "rule.yaml"
    )
    runtime = EdgeRuntime(settings)
    runtime.load_pipeline()
    assert runtime.pipeline is not None
    assert runtime.pipeline_error is None


def test_pause_and_resume_cycle(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    runtime.pause("shift change", by="operator-01")
    assert runtime.paused is True
    assert runtime.paused_reason == "shift change"
    assert runtime.paused_by == "operator-01"
    assert runtime.paused_at is not None
    runtime.resume()
    assert runtime.paused is False
    assert runtime.paused_reason is None
    assert runtime.paused_at is None


def test_device_status_faulted_when_pipeline_error(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    runtime.pipeline_error = "config broken"
    status = runtime.device_status(upload_pending=3)
    assert status["operational_state"] == "FAULTED"
    assert status["inspection_ready"] is False
    assert status["model_loaded"] is False
    assert "NOT_READY" in status["alerts"]
    assert status["upload_pending_count"] == 3
    assert status["central_connected"] is False


def test_device_status_initializing_without_error(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    status = runtime.device_status(upload_pending=0)
    assert status["operational_state"] == "INITIALIZING"
    assert status["inspection_ready"] is False
    assert status["current_product_model_version_id"] is None


def test_device_status_ready_with_pipeline(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    runtime.pipeline = _fake_pipeline()
    status = runtime.device_status(upload_pending=0)
    assert status["operational_state"] == "READY"
    assert status["inspection_ready"] is True
    assert status["model_loaded"] is True
    assert status["current_product_model_version_id"] == str(
        runtime.pipeline._product_manifest.model_version_id
    )
    assert status["current_component_model_version_id"] == str(
        runtime.pipeline._component_manifest.model_version_id
    )
    assert status["alerts"] == []


def test_device_status_paused_reports_not_ready(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    runtime.pipeline = _fake_pipeline()
    runtime.pause("lunch")
    status = runtime.device_status(upload_pending=0)
    assert status["operational_state"] == "PAUSED"
    assert status["inspection_ready"] is False
    assert "NOT_READY" in status["alerts"]


def test_device_status_disk_error_reports_low(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    def boom(_path: object) -> object:
        raise OSError("no disk")

    monkeypatch.setattr(shutil, "disk_usage", boom)
    runtime = EdgeRuntime(_settings(tmp_path))
    status = runtime.device_status(upload_pending=0)
    assert status["disk_free_bytes"] == 0
    assert "DISK_LOW" in status["alerts"]


def test_model_version_id_without_pipeline(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    assert runtime._model_version_id(runtime.pipeline, "product") is None
    assert runtime._model_version_id(runtime.pipeline, "component") is None


def test_model_version_id_with_pipeline(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    runtime.pipeline = _fake_pipeline()
    assert runtime._model_version_id(runtime.pipeline, "product") == str(
        runtime.pipeline._product_manifest.model_version_id
    )
    assert runtime._model_version_id(runtime.pipeline, "component") == str(
        runtime.pipeline._component_manifest.model_version_id
    )


def test_inspection_state(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    state = runtime.inspection_state(last_result="OK")
    assert state["window_active"] is False
    assert state["paused"] is False
    assert state["faulted"] is True
    assert state["last_result"] == "OK"
    runtime.pipeline = _fake_pipeline()
    runtime.pause("why")
    state = runtime.inspection_state(last_result=None)
    assert state["faulted"] is False
    assert state["paused"] is True
    assert state["paused_reason"] == "why"


def test_camera_state(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path, camera_width=1280, camera_height=720, camera_fps=30))
    camera = runtime.camera_state()
    assert camera["connected"] is True
    assert camera["source_width"] == 1280
    assert camera["source_height"] == 720
    assert camera["fps"] == 30
    assert camera["last_frame_at"] is None


def test_effective_configuration_without_pipeline(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    config = runtime.effective_configuration()
    assert config["revision"] == "local"
    assert config["managed"] == {}
    assert config["local_overrides"] == {}
    assert len(config["checksum_sha256"]) == 64


def test_effective_configuration_with_pipeline(tmp_path: Path) -> None:
    runtime = EdgeRuntime(_settings(tmp_path))
    runtime.pipeline = _fake_pipeline()
    config = runtime.effective_configuration()
    managed = config["managed"]
    assert managed["application_version"] == "0.1.0"
    assert managed["product_detection"]["confidence_threshold"] == 0.7
    assert managed["component_detection"]["components"] == {"component_a": 0.5, "component_b": 0.5}
    assert managed["roi"]["margin_x_ratio"] == 0.05
    assert managed["rule"]["rule_id"] == RULE_ID
    assert managed["rule"]["required_components"] == ["component_a", "component_b"]
    assert runtime.rule_snapshot is not None


def test_config_checksum_skips_unreadable_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    runtime = EdgeRuntime(_settings(tmp_path, config_path=missing))
    checksum = runtime._config_checksum()
    assert len(checksum) == 64
    assert checksum == runtime._config_checksum()


def test_build_pipeline_requires_config_and_rule(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        _build_pipeline(_settings(tmp_path))
    with pytest.raises(ConfigError):
        _build_pipeline(_settings(tmp_path, config_path=tmp_path / "x.yaml"))


def test_build_pipeline_constructs_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product_manifest = _fake_manifest()
    component_manifest = _fake_manifest()
    config = _fake_config()
    config.product_manifest = tmp_path / "product.json"
    config.component_manifest = tmp_path / "component.json"
    rule = _fake_rule()
    detector = object()
    pipeline = object()

    monkeypatch.setattr("assemblyvision_edge.config.load_pipeline_config", lambda path: config)
    monkeypatch.setattr(
        "assemblyvision_edge.config.load_rule_definition",
        lambda path, registry=None: rule,
    )
    monkeypatch.setattr(
        "assemblyvision_vision.manifests.load_model_manifest",
        lambda path: product_manifest if "product" in str(path) else component_manifest,
    )
    monkeypatch.setattr(
        "assemblyvision_edge.config.validate_model_version_declaration", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "assemblyvision_edge.config.validate_rule_component_compatibility", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "assemblyvision_edge.detection.ProductDetector.from_manifest", lambda *a, **k: detector
    )
    monkeypatch.setattr(
        "assemblyvision_edge.detection.ComponentDetector.from_manifest", lambda *a, **k: detector
    )
    monkeypatch.setattr("assemblyvision_vision.roi.roi_engine.ROIEngine", lambda config: object())
    monkeypatch.setattr(
        "assemblyvision_edge.pipeline.InspectionPipeline", lambda **kwargs: pipeline
    )

    settings = _settings(tmp_path, config_path=tmp_path / "p.yaml", rule_path=tmp_path / "r.yaml")
    result = _build_pipeline(settings)
    assert result is pipeline


def test_build_pipeline_raises_on_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(path: object) -> object:
        raise ConfigError("bad pipeline")

    monkeypatch.setattr("assemblyvision_edge.config.load_pipeline_config", broken)
    settings = _settings(tmp_path, config_path=tmp_path / "p.yaml", rule_path=tmp_path / "r.yaml")
    with pytest.raises(ConfigError):
        _build_pipeline(settings)
