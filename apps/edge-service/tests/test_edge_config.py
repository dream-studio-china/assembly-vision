"""Tests for multi-instance edge configuration (ADR-013)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from assemblyvision_domain.errors import ConfigError
from assemblyvision_edge.config import (
    EdgeConfig,
    load_edge_config,
    load_pipeline_config,
)


def _instance_yaml(instance_id: str = "line-1", **overrides: object) -> dict[str, object]:
    instance: dict[str, object] = {
        "instance_id": instance_id,
        "camera": {"source": "rtsp", "url": "rtsp://192.168.1.10/stream", "fps": 25},
        "models": {
            "product_manifest": "models/product-manifest.json",
            "component_manifest": "models/component-manifest.json",
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
        "rule": "rules/product-rule.yaml",
    }
    instance.update(overrides)
    return instance


def _write_edge_config(tmp_path: Path, instances: list[dict[str, object]]) -> Path:
    path = tmp_path / "edge.yaml"
    path.write_text(
        yaml.safe_dump({"application_version": "0.1.0", "instances": instances}),
        encoding="utf-8",
    )
    return path


def test_load_edge_config_parses_instances(tmp_path: Path) -> None:
    path = _write_edge_config(
        tmp_path,
        [
            _instance_yaml("line-1"),
            _instance_yaml(
                "line-2", camera={"source": "folder", "path": "images", "loop": True, "fps": 5}
            ),
        ],
    )
    config = load_edge_config(path)
    assert isinstance(config, EdgeConfig)
    assert config.application_version == "0.1.0"
    assert [instance.instance_id for instance in config.instances] == ["line-1", "line-2"]
    first = config.instances[0]
    assert first.device_id is None
    assert first.camera.source == "rtsp"
    assert first.camera.url == "rtsp://192.168.1.10/stream"
    assert first.camera.fps == 25.0
    assert first.inspection.enabled is False
    assert first.rule == (tmp_path / "rules" / "product-rule.yaml")
    assert first.pipeline.product_manifest == (tmp_path / "models" / "product-manifest.json")
    second = config.instances[1]
    assert second.camera.source == "folder"
    assert second.camera.path == (tmp_path / "images")
    assert second.camera.loop is True


def test_load_edge_config_device_id_defaults_and_validation(tmp_path: Path) -> None:
    valid_uuid = "12345678-1234-5678-1234-567812345678"
    path = _write_edge_config(tmp_path, [_instance_yaml("line-1", device_id=valid_uuid)])
    config = load_edge_config(path)
    assert config.instances[0].device_id == valid_uuid

    bad = _write_edge_config(tmp_path, [_instance_yaml("line-1", device_id="not-a-uuid")])
    with pytest.raises(ConfigError, match="device_id must be a valid UUID"):
        load_edge_config(bad)


def test_load_edge_config_rejects_duplicate_instance_id(tmp_path: Path) -> None:
    path = _write_edge_config(tmp_path, [_instance_yaml("line-1"), _instance_yaml("line-1")])
    with pytest.raises(ConfigError, match="duplicate instance_id"):
        load_edge_config(path)


def test_load_edge_config_rejects_unknown_source(tmp_path: Path) -> None:
    path = _write_edge_config(tmp_path, [_instance_yaml("line-1", camera={"source": "gimbal"})])
    with pytest.raises(ConfigError, match="not one of"):
        load_edge_config(path)


@pytest.mark.parametrize(
    "camera,message",
    [
        ({"source": "rtsp"}, "requires a url"),
        ({"source": "folder"}, "requires a path"),
        ({"source": "opencv-device"}, "requires a device"),
        ({"source": "video"}, "requires a path"),
        ({"source": "http-image"}, "requires a url"),
    ],
)
def test_load_edge_config_requires_fields(
    tmp_path: Path, camera: dict[str, object], message: str
) -> None:
    path = _write_edge_config(tmp_path, [_instance_yaml("line-1", camera=camera)])
    with pytest.raises(ConfigError, match=message):
        load_edge_config(path)


def test_load_edge_config_rejects_invalid_fps(tmp_path: Path) -> None:
    path = _write_edge_config(
        tmp_path, [_instance_yaml("line-1", camera={"source": "rtsp", "url": "rtsp://x", "fps": 0})]
    )
    with pytest.raises(ConfigError, match="fps must be positive"):
        load_edge_config(path)


def test_load_edge_config_rejects_unknown_top_level(tmp_path: Path) -> None:
    path = tmp_path / "edge.yaml"
    path.write_text(
        yaml.safe_dump({"application_version": "0.1.0", "cameras": []}), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="unknown keys"):
        load_edge_config(path)


def test_load_edge_config_rejects_empty_instances(tmp_path: Path) -> None:
    path = _write_edge_config(tmp_path, [])
    with pytest.raises(ConfigError, match="non-empty list"):
        load_edge_config(path)


def test_load_edge_config_inspection_enabled(tmp_path: Path) -> None:
    path = _write_edge_config(
        tmp_path,
        [_instance_yaml("line-1", inspection={"enabled": True})],
    )
    config = load_edge_config(path)
    assert config.instances[0].inspection.enabled is True


def test_camera_source_config_maps_to_frame_source_config(tmp_path: Path) -> None:
    path = _write_edge_config(
        tmp_path, [_instance_yaml("line-1", camera={"source": "folder", "path": "images"})]
    )
    camera = load_edge_config(path).instances[0].camera
    frame_config = camera.as_frame_source_config()
    assert frame_config.source == "folder"
    assert frame_config.path == camera.path
    assert frame_config.reconnect_initial_delay_ms == 250


def test_legacy_flat_config_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    instance = _instance_yaml()
    flat = {
        "application_version": "0.1.0",
        "models": instance["models"],
        "product_detection": instance["product_detection"],
        "component_detection": instance["component_detection"],
        "roi": instance["roi"],
    }
    path.write_text(yaml.safe_dump(flat), encoding="utf-8")
    config = load_pipeline_config(path)
    assert config.product_manifest == (tmp_path / "models" / "product-manifest.json")
    assert list(config.components) == ["component_a"]


def test_committed_camera_example_loads() -> None:
    example = Path(__file__).resolve().parents[3] / "config" / "examples" / "pipeline.cameras.yaml"
    config = load_edge_config(example)
    assert [instance.instance_id for instance in config.instances] == ["line-1", "line-2", "bench"]
    assert config.instances[0].camera.source == "rtsp"
    assert config.instances[1].camera.source == "video"
    assert config.instances[2].camera.source == "folder"
    assert config.instances[2].inspection.enabled is True
