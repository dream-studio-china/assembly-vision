"""Tests for multi-instance runtime wiring (ADR-013)."""

from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID, uuid5

import pytest
import yaml
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime, _instance_device_id
from PIL import Image

from tests.conftest import EXAMPLE_RULE

_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def _write_edge_config(
    tmp_path: Path, images: Path, *, enabled: bool = True, device_id: str | None = None
) -> Path:
    instance: dict[str, object] = {
        "instance_id": "line-1",
        "camera": {"source": "folder", "path": str(images), "fps": 100.0, "loop": True},
        "inspection": {"enabled": enabled},
        "models": {
            "product_manifest": "models/manifests/product-manifest.json",
            "component_manifest": "models/manifests/component-manifest.json",
        },
        "product_detection": {
            "model_version": "product-yolo-1.0.0",
            "confidence_threshold": 0.7,
            "iou_threshold": 0.5,
        },
        "component_detection": {
            "model_version": "component-yolo-1.0.0",
            "iou_threshold": 0.5,
            "components": {"component_a": {"observation_threshold": 0.5}},
        },
        "roi": {"margin_x_ratio": 0.05, "margin_y_ratio": 0.05},
        "rule": str(EXAMPLE_RULE),
    }
    if device_id is not None:
        instance["device_id"] = device_id
    path = tmp_path / "edge.yaml"
    path.write_text(
        yaml.safe_dump({"application_version": "0.1.0", "instances": [instance]}),
        encoding="utf-8",
    )
    return path


def _make_images(tmp_path: Path) -> Path:
    images = tmp_path / "images"
    images.mkdir()
    for i in range(2):
        Image.new("RGB", (64, 48), (i * 40, 128, 128)).save(images / f"img_{i}.png")
    return images


def test_instance_device_id_defaults_to_uuid5() -> None:
    from assemblyvision_edge.config import InstanceConfig as IC

    instance = IC(
        instance_id="line-1",
        device_id=None,
        camera=object(),  # type: ignore[arg-type]
        inspection=object(),  # type: ignore[arg-type]
        pipeline=object(),  # type: ignore[arg-type]
        rule=Path("rule.yaml"),
    )
    assert _instance_device_id(instance) == uuid5(_NAMESPACE, "line-1")

    explicit = IC(
        instance_id="line-1",
        device_id="12345678-1234-5678-1234-567812345678",
        camera=object(),  # type: ignore[arg-type]
        inspection=object(),  # type: ignore[arg-type]
        pipeline=object(),  # type: ignore[arg-type]
        rule=Path("rule.yaml"),
    )
    assert _instance_device_id(explicit) == UUID("12345678-1234-5678-1234-567812345678")


def test_load_instances_runs_inspection_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.api import state

    class FakePipeline:
        def __init__(self) -> None:
            self.count = 0

        def inspect_frame(self, frame: object, writer: object) -> object:
            self.count += 1
            from types import SimpleNamespace

            return SimpleNamespace(decision=SimpleNamespace(business_result="OK"))

    monkeypatch.setattr(
        state, "_build_instance_pipeline", lambda instance, rule_registry=None: FakePipeline()
    )
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    runtime = EdgeRuntime(settings)
    config_path = _write_edge_config(tmp_path, _make_images(tmp_path))
    runtime.load_instances(config_path)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            pipeline = runtime.instances["line-1"].pipeline
            if pipeline is not None and pipeline.count > 0:
                break
            time.sleep(0.05)
        pipeline = runtime.instances["line-1"].pipeline
        assert pipeline is not None and pipeline.count > 0
        assert runtime.camera_manager is not None
        assert runtime.camera_manager.latest_frame("line-1") is not None
    finally:
        runtime.shutdown()


def test_load_instances_reports_pipeline_error_without_crash(
    tmp_path: Path,
) -> None:
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    runtime = EdgeRuntime(settings)
    # No manifest files exist at the resolved paths -> pipeline build fails,
    # but the camera source still starts and the instance is reported.
    config_path = _write_edge_config(tmp_path, _make_images(tmp_path))
    runtime.load_instances(config_path)
    try:
        instance = runtime.instances["line-1"]
        assert instance.pipeline_error is not None
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if (
                runtime.camera_manager is not None
                and runtime.camera_manager.latest_frame("line-1") is not None
            ):
                break
            time.sleep(0.05)
        assert runtime.camera_manager is not None
        assert runtime.camera_manager.latest_frame("line-1") is not None
    finally:
        runtime.shutdown()
