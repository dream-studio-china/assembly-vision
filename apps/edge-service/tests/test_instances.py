"""Tests for multi-instance runtime wiring (ADR-013)."""

from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID, uuid5

import pytest
import yaml
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime, _instance_device_id
from assemblyvision_vision.sources.frame_source import CapturedFrame
from PIL import Image

from tests.conftest import EXAMPLE_RULE

_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def _write_edge_config(
    tmp_path: Path,
    images: Path,
    *,
    enabled: bool = True,
    device_id: str | None = None,
    temporal: dict[str, object] | None = None,
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
    if temporal is not None:
        instance["temporal"] = temporal
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


def _instance_yaml(instance_id: str, camera: dict[str, object]) -> dict[str, object]:
    return {
        "instance_id": instance_id,
        "camera": camera,
        "inspection": {"enabled": True},
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


def _write_multi_edge_config(tmp_path: Path, instances: list[dict[str, object]]) -> Path:
    path = tmp_path / "edge.yaml"
    path.write_text(
        yaml.safe_dump({"application_version": "0.1.0", "instances": instances}),
        encoding="utf-8",
    )
    return path


def test_instance_device_id_defaults_to_uuid5() -> None:
    from assemblyvision_edge.config import InstanceConfig as IC

    instance = IC(
        instance_id="line-1",
        device_id=None,
        camera=object(),  # type: ignore[arg-type]
        inspection=object(),  # type: ignore[arg-type]
        temporal=None,
        pipeline=object(),  # type: ignore[arg-type]
        rule=Path("rule.yaml"),
    )
    assert _instance_device_id(instance) == uuid5(_NAMESPACE, "line-1")

    explicit = IC(
        instance_id="line-1",
        device_id="12345678-1234-5678-1234-567812345678",
        camera=object(),  # type: ignore[arg-type]
        inspection=object(),  # type: ignore[arg-type]
        temporal=None,
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


def test_missing_folder_source_is_unavailable_not_fatal(tmp_path: Path) -> None:
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    runtime = EdgeRuntime(settings)
    good = _make_images(tmp_path)
    bad = _instance_yaml(
        "line-bad",
        {"source": "folder", "path": str(tmp_path / "missing"), "fps": 100.0, "loop": True},
    )
    good_instance = _instance_yaml(
        "line-good",
        {"source": "folder", "path": str(good), "fps": 100.0, "loop": True},
    )
    config_path = _write_multi_edge_config(tmp_path, [bad, good_instance])
    runtime.load_instances(config_path)
    try:
        assert "line-bad" in runtime.instances
        assert "line-good" in runtime.instances
        # The invalid instance is present with a stable unavailable code and is
        # not usable, while the valid instance streams frames.
        bad_state = runtime.camera_manager.state("line-bad")
        assert bad_state is not None
        assert bad_state.error_code == "CAMERA_UNAVAILABLE"
        assert bad_state.connected is False
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if runtime.camera_manager.latest_frame("line-good") is not None:
                break
            time.sleep(0.05)
        assert runtime.camera_manager.latest_frame("line-good") is not None
    finally:
        runtime.shutdown()


def test_inspection_loop_no_silent_frame_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from assemblyvision_edge.api import state as state_module

    inspected: list[int] = []

    class SlowPipeline:
        def inspect_frame(self, frame: CapturedFrame, writer: object) -> object:
            inspected.append(frame.sequence)
            time.sleep(0.05)
            return SimpleNamespace(decision=SimpleNamespace(business_result="OK"))

    monkeypatch.setattr(
        state_module,
        "_build_instance_pipeline",
        lambda instance, rule_registry=None: SlowPipeline(),
    )
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    runtime = EdgeRuntime(settings)
    config_path = _write_edge_config(tmp_path, _make_images(tmp_path))
    runtime.load_instances(config_path)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if len(inspected) >= 6:
                break
            time.sleep(0.05)
        assert len(inspected) >= 6
        # Accepted frames are inspected in sequence without gaps; overflow is
        # surfaced explicitly instead of being silently discarded (F1).
        assert inspected == list(range(1, len(inspected) + 1))
        state = runtime.camera_manager.state("line-1")
        assert state is not None
        assert state.frames_dropped > 0
        assert state.degraded is True
    finally:
        runtime.shutdown()


def test_pause_stops_inspection_and_status_reports_paused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from assemblyvision_edge.api import state as state_module

    inspected: list[int] = []

    class FastPipeline:
        _product_manifest = SimpleNamespace(
            model_version_id=UUID("00000000-0000-0000-0000-000000000001")
        )
        _component_manifest = SimpleNamespace(
            model_version_id=UUID("00000000-0000-0000-0000-000000000002")
        )

        def inspect_frame(self, frame: CapturedFrame, writer: object) -> object:
            inspected.append(frame.sequence)
            return SimpleNamespace(decision=SimpleNamespace(business_result="OK"))

    monkeypatch.setattr(
        state_module,
        "_build_instance_pipeline",
        lambda instance, rule_registry=None: FastPipeline(),
    )
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    runtime = EdgeRuntime(settings)
    config_path = _write_edge_config(tmp_path, _make_images(tmp_path))
    runtime.load_instances(config_path)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if len(inspected) >= 1:
                break
            time.sleep(0.05)
        assert len(inspected) >= 1
        runtime.pause("shift change")
        time.sleep(0.2)
        settled = len(inspected)
        time.sleep(0.2)
        assert len(inspected) == settled  # no further inspections while paused
        status = runtime.device_status(0)
        assert status["operational_state"] == "PAUSED"
        assert status["inspection_ready"] is False
        assert "NOT_READY" in status["alerts"]
        runtime.resume()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if len(inspected) > settled:
                break
            time.sleep(0.05)
        assert len(inspected) > settled
    finally:
        runtime.shutdown()


def test_temporal_loop_expires_idle_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A final product with no further frames is finalized by idle expiry.

    The folder source is non-looping and holds exactly two images, so after
    both frames the inspection loop only sees empty polls. The idle window must
    be closed as a normal record by ``expire()`` rather than left open until
    shutdown discards it as interrupted (PR-015 F2).
    """
    from types import SimpleNamespace
    from uuid import uuid4

    from assemblyvision_edge.api import state as state_module
    from assemblyvision_edge.temporal.window_manager import FrameObservation

    finalized: list[int] = []

    class TemporalPipeline:
        def frame_observations(self, frame: CapturedFrame) -> FrameObservation:
            return FrameObservation(
                frame_id=uuid4(),
                sequence=frame.sequence,
                captured_at=frame.wall_clock_utc,
                quality_usable=True,
                product_detected=True,
                roi_valid=True,
                inference_valid=True,
                product_detection=None,
                roi_result=None,
                observations=[],
                image=frame.image,
                product_identity="test-product",
            )

        def inspect_window(self, window: object, writer: object) -> object:
            finalized.append(len(window.frames))  # type: ignore[attr-defined]
            return SimpleNamespace(decision=SimpleNamespace(business_result="OK"))

    monkeypatch.setattr(
        state_module,
        "_build_instance_pipeline",
        lambda instance, rule_registry=None: TemporalPipeline(),
    )
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    runtime = EdgeRuntime(settings)
    images = _make_images(tmp_path)
    instance = _instance_yaml("line-1", {"source": "folder", "path": str(images), "fps": 20.0})
    instance["temporal"] = {
        "window_strategy": "identity",
        "minimum_valid_frames": 1,
        "maximum_window_ms": 1000,
    }
    config_path = _write_multi_edge_config(tmp_path, [instance])
    runtime.load_instances(config_path)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            # Both frames arrive, then the idle window must expire on its own.
            if finalized:
                break
            time.sleep(0.05)
        assert finalized == [2], "idle window was not finalized with both frames"
        runtime.shutdown()
        # Normal expiry leaves no active window, so shutdown adds no record.
        assert len(finalized) == 1
    finally:
        runtime.shutdown()


def test_temporal_loop_emits_windowed_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from assemblyvision_edge.api import state as state_module
    from assemblyvision_edge.temporal.window_manager import FrameObservation

    finalized: list[int] = []

    class TemporalPipeline:
        def frame_observations(self, frame: CapturedFrame) -> FrameObservation:
            return FrameObservation(
                frame_id=uuid4(),
                sequence=frame.sequence,
                captured_at=frame.wall_clock_utc,
                quality_usable=True,
                product_detected=True,
                roi_valid=True,
                inference_valid=True,
                product_detection=None,
                roi_result=None,
                observations=[],
                image=frame.image,
                product_identity="test-product",
            )

        def inspect_window(self, window: object, writer: object) -> object:
            finalized.append(len(window.frames))  # type: ignore[attr-defined]
            return SimpleNamespace(decision=SimpleNamespace(business_result="OK"))

    monkeypatch.setattr(
        state_module,
        "_build_instance_pipeline",
        lambda instance, rule_registry=None: TemporalPipeline(),
    )
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    runtime = EdgeRuntime(settings)
    config_path = _write_edge_config(
        tmp_path,
        _make_images(tmp_path),
        temporal={
            "window_strategy": "identity",
            "minimum_valid_frames": 1,
            "maximum_window_ms": 200,
        },
    )
    runtime.load_instances(config_path)
    try:
        assert runtime.instances["line-1"].temporal is not None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if finalized:
                break
            time.sleep(0.05)
        assert finalized, "temporal loop never finalized a window"
        # Each finalized window groups a bounded set of frames into one record.
        assert all(1 <= count <= 40 for count in finalized)
        assert runtime.instances["line-1"].last_result == "OK"
    finally:
        runtime.shutdown()
