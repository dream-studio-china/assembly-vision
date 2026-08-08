"""Tests for the gated web dev test endpoints (ADR-014)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.models import (
    BarcodeResult,
    BusinessResult,
    FrameQualitySummary,
    InspectionDecision,
    InspectionLifecycle,
    InspectionRecord,
    InternalDecision,
    ProductResolution,
)
from assemblyvision_edge.api.deps import get_runtime, get_settings
from assemblyvision_edge.api.problems import install_problem_handlers
from assemblyvision_edge.api.routers.dev import router as dev_router
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_vision.sources.frame_source import CapturedFrame
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image


class FakePipeline:
    def __init__(self, alternate: bool = False) -> None:
        self.calls: list[tuple[CapturedFrame, object | None]] = []
        self.alternate = alternate

    def inspect_frame(self, frame: CapturedFrame, writer: object | None = None) -> InspectionRecord:
        self.calls.append((frame, writer))
        result = "NG" if (self.alternate and frame.sequence % 2 == 0) else "OK"
        return InspectionRecord(
            inspection_id=uuid4(),
            device_id=uuid4(),
            device_sequence=1,
            lifecycle_status=InspectionLifecycle.COMPLETED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            barcode_result=BarcodeResult(status="NOT_REQUIRED"),
            product_resolution=ProductResolution(
                status="RESOLVED", source="CONFIGURED_DEFAULT", product_code="test"
            ),
            product_detection=None,
            roi_result=None,
            frame_quality_summary=FrameQualitySummary(
                total_frame_count=1, usable_frame_count=1, rejected_frame_count=0
            ),
            application_version="0.1.0",
            product_model_version_id=uuid4(),
            product_model_checksum_sha256="0" * 64,
            component_model_version_id=uuid4(),
            component_model_checksum_sha256="0" * 64,
            rule_version_id=uuid4(),
            aggregation_policy_version="single-frame-mvp-1",
            evidence=[],
            media=[],
            decision=InspectionDecision(
                internal_decision=InternalDecision(result),
                business_result=BusinessResult(result),
                missing_components=[],
                low_confidence_components=[],
                reason_codes=["TEST_REASON"] if result == "NG" else [],
                decided_at=datetime.now(UTC),
            ),
            synchronization_status="LOCAL_ONLY",
            processing_ms=1,
        )


class StubInstance:
    def __init__(self, pipeline: FakePipeline | None) -> None:
        self.pipeline = pipeline


class StubRuntime:
    def __init__(self, tmp_path: Path, *, instances: bool = False, alternate: bool = False) -> None:
        self._settings = ServerSettings(
            output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3"
        )
        self.pipeline: FakePipeline | None = None
        self.instances: dict[str, StubInstance] = {}
        if instances:
            self.instances = {
                "line-1": StubInstance(FakePipeline(alternate=alternate)),
                "line-2": StubInstance(None),
            }
        else:
            self.pipeline = FakePipeline(alternate=alternate)


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "blue").save(buffer, format="JPEG")
    return buffer.getvalue()


def _app(runtime: StubRuntime, *, enabled: bool = True, root: Path | None = None) -> TestClient:
    settings = ServerSettings(
        output_root=(root or Path("/nonexistent")) / "out",
        db_path=(root or Path("/nonexistent")) / "edge.sqlite3",
        enable_web_test=enabled,
    )
    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(dev_router)
    app.state.settings = settings
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_dev_frame_disabled_returns_404(tmp_path: Path) -> None:
    client = _app(StubRuntime(tmp_path), enabled=False)
    response = client.post("/dev/inspect-frame", content=_jpeg_bytes())
    assert response.status_code == 404
    assert response.json()["code"] == "DEV_TOOLS_DISABLED"


def test_dev_frame_inspects_and_persists_by_default(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path)
    client = _app(runtime)
    response = client.post("/dev/inspect-frame", content=_jpeg_bytes())
    assert response.status_code == 200
    assert response.json()["decision"]["business_result"] == "OK"
    assert runtime.pipeline is not None and len(runtime.pipeline.calls) == 1
    _frame, writer = runtime.pipeline.calls[0]
    assert writer is not None


def test_dev_frame_persist_false_skips_writer(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path)
    client = _app(runtime)
    response = client.post("/dev/inspect-frame", params={"persist": "false"}, content=_jpeg_bytes())
    assert response.status_code == 200
    assert runtime.pipeline is not None
    _frame, writer = runtime.pipeline.calls[0]
    assert writer is None


def test_dev_frame_uses_instance_id(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path, instances=True)
    client = _app(runtime)
    response = client.post(
        "/dev/inspect-frame", params={"instance_id": "line-1"}, content=_jpeg_bytes()
    )
    assert response.status_code == 200
    pipeline = runtime.instances["line-1"].pipeline
    assert pipeline is not None and len(pipeline.calls) == 1


def test_dev_frame_unknown_instance_404(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path, instances=True)
    client = _app(runtime)
    response = client.post(
        "/dev/inspect-frame", params={"instance_id": "nope"}, content=_jpeg_bytes()
    )
    assert response.status_code == 404
    assert response.json()["code"] == "INSTANCE_NOT_FOUND"


def test_dev_frame_unloaded_pipeline_503(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path, instances=True)
    client = _app(runtime)
    response = client.post(
        "/dev/inspect-frame", params={"instance_id": "line-2"}, content=_jpeg_bytes()
    )
    assert response.status_code == 503
    assert response.json()["code"] == "PIPELINE_UNAVAILABLE"


def test_dev_frame_invalid_image_400(tmp_path: Path) -> None:
    client = _app(StubRuntime(tmp_path))
    response = client.post("/dev/inspect-frame", content=b"not an image")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_IMAGE"


def test_dev_frame_empty_body_400(tmp_path: Path) -> None:
    client = _app(StubRuntime(tmp_path))
    response = client.post("/dev/inspect-frame", content=b"")
    assert response.status_code == 400
    assert response.json()["code"] == "EMPTY_BODY"


def _make_video(tmp_path: Path, count: int = 4) -> bytes:
    import cv2

    path = tmp_path / "sample.avi"
    fourcc = ord("M") | (ord("J") << 8) | (ord("P") << 16) | (ord("G") << 24)
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (64, 48))
    import numpy as np

    for i in range(count):
        frame = np.zeros((48, 64, 3), np.uint8)
        frame[:, :, 0] = (i * 40) % 256
        writer.write(frame)
    writer.release()
    return path.read_bytes()


def test_dev_video_returns_per_frame_summary(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path, alternate=True)
    client = _app(runtime)
    response = client.post("/dev/inspect-video", content=_make_video(tmp_path, count=4))
    assert response.status_code == 200
    body = response.json()
    assert body["instance_id"] == "default"
    assert body["analyzed_frames"] == 4
    assert body["ok_count"] == 2
    assert body["ng_count"] == 2
    assert [frame["index"] for frame in body["frames"]] == [1, 2, 3, 4]
    # NG frames carry their reason codes.
    assert body["frames"][1]["reason_codes"] == ["TEST_REASON"]


def test_dev_video_step_sampling(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path, alternate=True)
    client = _app(runtime)
    response = client.post(
        "/dev/inspect-video", params={"step": "2"}, content=_make_video(tmp_path, count=4)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["analyzed_frames"] == 2
    assert [frame["index"] for frame in body["frames"]] == [1, 3]


def test_dev_video_caps_analyzed_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from assemblyvision_edge.api.routers import dev

    monkeypatch.setattr(dev, "_MAX_VIDEO_FRAMES", 2)
    client = _app(StubRuntime(tmp_path))
    response = client.post("/dev/inspect-video", content=_make_video(tmp_path, count=4))
    assert response.status_code == 200
    assert response.json()["analyzed_frames"] == 2


def test_dev_video_invalid_body_400(tmp_path: Path) -> None:
    client = _app(StubRuntime(tmp_path))
    response = client.post("/dev/inspect-video", content=b"not a video")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_VIDEO"


def test_dev_video_too_large_413(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from assemblyvision_edge.api.routers import dev

    monkeypatch.setattr(dev, "_MAX_VIDEO_BYTES", 10)
    client = _app(StubRuntime(tmp_path))
    response = client.post("/dev/inspect-video", content=b"x" * 20)
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
