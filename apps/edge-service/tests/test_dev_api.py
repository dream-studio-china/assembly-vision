"""Tests for the gated web dev test endpoints (ADR-014)."""

from __future__ import annotations

import io
import struct
import zlib
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import cast
from uuid import uuid4

import anyio
import httpx
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
from assemblyvision_edge.output.writer import OutputWriter
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


class PublishingPipeline(FakePipeline):
    """FakePipeline that also publishes the evidence bundle through the writer."""

    def inspect_frame(self, frame: CapturedFrame, writer: object | None = None) -> InspectionRecord:
        record = super().inspect_frame(frame, writer)
        if writer is not None:
            record = cast(OutputWriter, writer).save(
                record, full_frame=None, roi_image=None, annotated=None
            )
        return record


class BarcodePipeline(FakePipeline):
    barcode_identity_enabled = True

    def __init__(self) -> None:
        super().__init__()
        self.simulated_input: str | None = None

    def resolve_dev_identity(self, image: Image.Image, simulated_input: str | None) -> object:
        self.simulated_input = simulated_input
        return object()

    def inspect_frame(
        self, frame: CapturedFrame, writer: object | None = None, *, identity: object | None = None
    ) -> InspectionRecord:
        assert identity is not None
        return super().inspect_frame(frame, writer)


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


class FakeFrameSource:
    """Yields numbered frames without decoding, for decode-budget tests."""

    def __init__(self, count: int) -> None:
        self.count = count

    def frames(self, stop: Event) -> Iterator[CapturedFrame]:
        for sequence in range(1, self.count + 1):
            yield CapturedFrame(
                monotonic_ts_ns=0,
                wall_clock_utc=datetime.now(UTC),
                sequence=sequence,
                pixel_format="RGB",
                status="OK",
                image=Image.new("RGB", (8, 8)),
            )


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "blue").save(buffer, format="JPEG")
    return buffer.getvalue()


def _build_app(runtime: StubRuntime, *, enabled: bool = True, root: Path | None = None) -> FastAPI:
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
    return app


def _app(runtime: StubRuntime, *, enabled: bool = True, root: Path | None = None) -> TestClient:
    return TestClient(_build_app(runtime, enabled=enabled, root=root))


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


def test_dev_frame_passes_simulated_keyboard_barcode_to_pipeline(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path)
    pipeline = BarcodePipeline()
    runtime.pipeline = pipeline

    response = _app(runtime).post(
        "/dev/inspect-frame", params={"barcode": "ABC-001"}, content=_jpeg_bytes()
    )

    assert response.status_code == 200
    assert pipeline.simulated_input == "ABC-001"


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


def _tiny_png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("1", (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


def _png_header(width: int, height: int) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def test_dev_frame_rejects_oversize_streamed_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.api.routers import dev

    monkeypatch.setattr(dev, "_MAX_IMAGE_BYTES", 10)
    runtime = StubRuntime(tmp_path)

    async def oversized_body() -> AsyncIterator[bytes]:
        yield b"x" * 10
        yield b"y" * 10
        raise AssertionError("server read past the image byte limit")

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=_build_app(runtime), raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/dev/inspect-frame", content=oversized_body())
        assert response.status_code == 413
        assert response.json()["code"] == "PAYLOAD_TOO_LARGE"

    anyio.run(scenario)
    assert runtime.pipeline is not None
    assert runtime.pipeline.calls == []


def test_dev_frame_rejects_pixel_limit(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path)
    client = _app(runtime)
    response = client.post("/dev/inspect-frame", content=_tiny_png(10000, 5001))
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_IMAGE"
    assert runtime.pipeline is not None and runtime.pipeline.calls == []


def test_dev_frame_rejects_dimension_limit(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path)
    client = _app(runtime)
    response = client.post("/dev/inspect-frame", content=_tiny_png(13000, 1000))
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_IMAGE"
    assert runtime.pipeline is not None and runtime.pipeline.calls == []


def test_dev_frame_decompression_bomb_400(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path)
    client = _app(runtime)
    response = client.post("/dev/inspect-frame", content=_png_header(60000, 60000))
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_IMAGE"
    assert runtime.pipeline is not None and runtime.pipeline.calls == []


def test_dev_video_rejects_step_over_limit(tmp_path: Path) -> None:
    runtime = StubRuntime(tmp_path)
    client = _app(runtime)
    response = client.post(
        "/dev/inspect-video", params={"step": "100000"}, content=_make_video(tmp_path, count=4)
    )
    assert response.status_code == 422


def test_dev_video_truncated_when_decode_budget_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.api.routers import dev

    monkeypatch.setattr(dev, "_MAX_DECODED_FRAMES", 3)
    monkeypatch.setattr(dev, "VideoFrameSource", lambda path: FakeFrameSource(count=10))
    runtime = StubRuntime(tmp_path)
    client = _app(runtime)
    response = client.post("/dev/inspect-video", content=b"fake-video")
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert body["analyzed_frames"] == 3


def test_dev_video_truncated_when_decode_time_budget_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.api.routers import dev

    class FakeClock:
        def __init__(self) -> None:
            self._elapsed = 0.0

        def monotonic(self) -> float:
            self._elapsed += 1.0
            return self._elapsed

    monkeypatch.setattr(dev, "_MAX_VIDEO_DECODE_SECONDS", 0)
    monkeypatch.setattr(dev, "time", FakeClock())
    monkeypatch.setattr(dev, "VideoFrameSource", lambda path: FakeFrameSource(count=10))
    runtime = StubRuntime(tmp_path)
    client = _app(runtime)
    response = client.post("/dev/inspect-video", content=b"fake-video")
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert body["analyzed_frames"] == 0


def _full_app(tmp_path: Path, *, enable_web_test: bool) -> tuple[FastAPI, StubRuntime]:
    """Full ``create_app`` instance with a real output root, db, and fake pipeline.

    The runtime override matches the app settings so the output writer and the
    startup-opened repository point at the same filesystem and database paths.
    """
    from assemblyvision_edge.api.app import create_app
    from assemblyvision_edge.api.deps import get_runtime

    settings = ServerSettings(
        output_root=tmp_path / "out",
        db_path=tmp_path / "edge.sqlite3",
        enable_web_test=enable_web_test,
        api_token="test-edge-token",  # noqa: S106 - test fixture credential
    )
    runtime = StubRuntime(tmp_path)
    runtime.pipeline = PublishingPipeline()
    app = create_app(settings)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app, runtime


def test_dev_frame_persisted_is_visible_without_restart(tmp_path: Path) -> None:
    """F7: a persisted dev inspection appears in history and detail immediately.

    The bundle is imported into the SQLite projection during the request, so
    the record must be queryable before any process restart.
    """
    app, _runtime = _full_app(tmp_path, enable_web_test=True)
    headers = {"Authorization": "Bearer test-edge-token"}
    with TestClient(app) as client:
        posted = client.post("/api/v1/dev/inspect-frame", headers=headers, content=_jpeg_bytes())
        assert posted.status_code == 200
        inspection_id = posted.json()["inspection_id"]

        detail = client.get(f"/api/v1/inspections/{inspection_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["inspection_id"] == inspection_id

        history = client.get("/api/v1/inspections", headers=headers)
        assert history.status_code == 200
        ids = [item["inspection_id"] for item in history.json()["items"]]
        assert inspection_id in ids


def test_dev_frame_persist_false_creates_no_projection(tmp_path: Path) -> None:
    """F7: persist=false publishes no bundle and imports no projection record."""
    app, _runtime = _full_app(tmp_path, enable_web_test=True)
    headers = {"Authorization": "Bearer test-edge-token"}
    with TestClient(app) as client:
        posted = client.post(
            "/api/v1/dev/inspect-frame",
            headers=headers,
            params={"persist": "false"},
            content=_jpeg_bytes(),
        )
        assert posted.status_code == 200
        inspection_id = posted.json()["inspection_id"]

        detail = client.get(f"/api/v1/inspections/{inspection_id}", headers=headers)
        assert detail.status_code == 404
        history = client.get("/api/v1/inspections", headers=headers)
        ids = [item["inspection_id"] for item in history.json()["items"]]
        assert inspection_id not in ids


def test_dev_persisted_projection_survives_restart_reconcile(tmp_path: Path) -> None:
    """F7: the imported projection is content-identical to the published bundle.

    The dev route imports the record returned by the pipeline; restart
    reconciliation re-reads the same bundle from disk. Identical content means
    the second import is a content-hash no-op, so the record is never
    duplicated and reconcile reports nothing new.
    """
    from assemblyvision_edge.output.writer import OutputWriter
    from assemblyvision_edge.persistence.reconcile import reconcile_output_root
    from assemblyvision_edge.persistence.repository import EdgeRepository

    output_root = tmp_path / "out"
    pipeline = PublishingPipeline()
    writer = OutputWriter(output_root)
    frame = CapturedFrame(
        monotonic_ts_ns=0,
        wall_clock_utc=datetime.now(UTC),
        sequence=1,
        pixel_format="RGB",
        status="OK",
        image=Image.new("RGB", (8, 8)),
    )
    record = pipeline.inspect_frame(frame, writer)
    bundle = (output_root / str(record.inspection_id) / "inspection.json").read_text(
        encoding="utf-8"
    )
    reparsed = InspectionRecord.model_validate_json(bundle)
    assert record.model_dump(mode="json") == reparsed.model_dump(mode="json")

    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert repository.upsert_inspection(record) == "inserted"
        assert reconcile_output_root(repository, output_root) == 0
        assert repository.upsert_inspection(reparsed) == "unchanged"
        page = repository.list_inspections()
        assert [str(i.inspection_id) for i in page.items] == [str(record.inspection_id)]
    finally:
        repository.close()


def test_dev_disabled_returns_404_before_auth(tmp_path: Path) -> None:
    """F8: the enablement gate runs before viewer authentication.

    With an API token configured but web tests disabled, both anonymous and
    authenticated dev requests must receive 404 DEV_TOOLS_DISABLED, not 401.
    """
    app, _runtime = _full_app(tmp_path, enable_web_test=False)
    with TestClient(app) as client:
        anon = client.post("/api/v1/dev/inspect-frame", content=_jpeg_bytes())
        assert anon.status_code == 404
        assert anon.json()["code"] == "DEV_TOOLS_DISABLED"

        authed = client.post(
            "/api/v1/dev/inspect-frame",
            headers={"Authorization": "Bearer test-edge-token"},
            content=_jpeg_bytes(),
        )
        assert authed.status_code == 404
        assert authed.json()["code"] == "DEV_TOOLS_DISABLED"


def test_dev_enabled_still_requires_viewer(tmp_path: Path) -> None:
    """F8: when enabled, the dev endpoints keep viewer authentication."""
    app, _runtime = _full_app(tmp_path, enable_web_test=True)
    with TestClient(app) as client:
        anon = client.post("/api/v1/dev/inspect-frame", content=_jpeg_bytes())
        assert anon.status_code == 401
        assert anon.json()["code"] == "UNAUTHENTICATED"

        # A valid bearer passes authentication and reaches the handler, which
        # rejects the empty body before any pipeline is invoked.
        authed = client.post(
            "/api/v1/dev/inspect-frame",
            headers={"Authorization": "Bearer test-edge-token"},
            content=b"",
        )
        assert authed.status_code == 400
        assert authed.json()["code"] == "EMPTY_BODY"
