"""Tests for the gated web dev test endpoints (ADR-014)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from assemblyvision_domain.models import (
    BarcodeResult,
    BusinessResult,
    FrameQualitySummary,
    InspectionDecision,
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
    def __init__(self) -> None:
        self.calls: list[tuple[CapturedFrame, object | None]] = []

    def inspect_frame(self, frame: CapturedFrame, writer: object | None = None) -> InspectionRecord:
        self.calls.append((frame, writer))
        return InspectionRecord(
            inspection_id=uuid4(),
            device_id=uuid4(),
            device_sequence=1,
            lifecycle_status="COMPLETED",
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
                internal_decision=InternalDecision.OK,
                business_result=BusinessResult.OK,
                missing_components=[],
                low_confidence_components=[],
                reason_codes=[],
                decided_at=datetime.now(UTC),
            ),
            synchronization_status="LOCAL_ONLY",
            processing_ms=1,
        )


class StubInstance:
    def __init__(self, pipeline: FakePipeline | None) -> None:
        self.pipeline = pipeline


class StubRuntime:
    def __init__(self, tmp_path: Path, *, instances: bool = False) -> None:
        self._settings = ServerSettings(
            output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3"
        )
        self.pipeline: FakePipeline | None = None
        self.instances: dict[str, StubInstance] = {}
        if instances:
            self.instances = {
                "line-1": StubInstance(FakePipeline()),
                "line-2": StubInstance(None),
            }
        else:
            self.pipeline = FakePipeline()


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "blue").save(buffer, format="JPEG")
    return buffer.getvalue()


def _app(runtime: StubRuntime, *, enabled: bool = True) -> TestClient:
    settings = ServerSettings(
        output_root=Path("/tmp/out"),
        db_path=Path("/tmp/edge.sqlite3"),
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
