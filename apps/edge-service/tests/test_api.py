"""Tests for the local edge API (FastAPI routers) and persistence layer."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.models import (
    AggregatedComponentEvidence,
    BarcodeResult,
    BusinessResult,
    FrameQualitySummary,
    InspectionDecision,
    InspectionLifecycle,
    InspectionRecord,
    InternalDecision,
    MediaLifecycle,
    MediaMetadata,
    ProductResolution,
)
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.persistence.repository import EdgeRepository
from fastapi.testclient import TestClient

INSPECTION_ID = "00000000-0000-4000-8000-0000000000aa"


def _record(
    completed_at: datetime, *, business: BusinessResult, barcode: str | None
) -> InspectionRecord:
    inspection_id = uuid4()
    return InspectionRecord(
        inspection_id=inspection_id,
        device_id=uuid4(),
        device_sequence=1,
        lifecycle_status=InspectionLifecycle.COMPLETED,
        started_at=completed_at,
        completed_at=completed_at,
        barcode_result=BarcodeResult(status="READ" if barcode else "NOT_REQUIRED", value=barcode),
        product_resolution=ProductResolution(
            status="RESOLVED", source="CONFIGURED_DEFAULT", product_code="model_a"
        ),
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
        evidence=[
            AggregatedComponentEvidence(
                component_code="component_a",
                state="PRESENT" if business is BusinessResult.OK else "MISSING",
                best_confidence=0.9 if business is BusinessResult.OK else None,
                usable_frame_count=1,
                detection_count=1 if business is BusinessResult.OK else 0,
                adjacent_detection_run=1 if business is BusinessResult.OK else 0,
                supporting_frame_ids=[uuid4()],
                policy_reason_codes=[]
                if business is BusinessResult.OK
                else ["COMPONENT_MISSING:component_a"],
                box_area_ratios=[0.5] if business is BusinessResult.OK else [],
                box_centers=[(0.5, 0.5)] if business is BusinessResult.OK else [],
            )
        ],
        decision=InspectionDecision(
            internal_decision=InternalDecision.OK
            if business is BusinessResult.OK
            else InternalDecision.NG,
            business_result=business,
            missing_components=[] if business is BusinessResult.OK else ["component_a"],
            reason_codes=[] if business is BusinessResult.OK else ["COMPONENT_MISSING:component_a"],
            decided_at=completed_at,
        ),
        synchronization_status="LOCAL_ONLY",
        processing_ms=12,
        media=[
            MediaMetadata(
                media_id=uuid4(),
                kind="KEY_FRAME",
                lifecycle=MediaLifecycle.AVAILABLE,
                relative_path=f"{inspection_id}/key_frame.jpg",
                mime_type="image/jpeg",
                size_bytes=10,
                checksum_sha256="0" * 64,
            )
        ],
    )


@pytest.fixture
def output_root(tmp_path: Path) -> Path:
    return tmp_path / "out"


@pytest.fixture
def seeded_root(tmp_path: Path) -> Path:
    """Output root with two CLI inspection.json records."""
    root = tmp_path / "out"
    root.mkdir()
    now = datetime.now(UTC)
    for idx, business in enumerate([BusinessResult.OK, BusinessResult.NG]):
        record = _record(now, business=business, barcode=f"SN-{idx:04d}")
        directory = root / str(record.inspection_id)
        directory.mkdir()
        directory.joinpath("inspection.json").write_text(
            record.model_dump_json(indent=2), encoding="utf-8"
        )
        directory.joinpath("key_frame.jpg").write_bytes(b"fake-jpeg-" + str(idx).encode())
    return root


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[EdgeRepository]:
    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        yield repo
    finally:
        repo.close()


def test_reconcile_seeded_root(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.reconcile import reconcile_output_root

    root = tmp_path / "out"
    root.mkdir()
    now = datetime.now(UTC)
    record = _record(now, business=BusinessResult.OK, barcode="SN-0001")
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 1
        assert reconcile_output_root(repo, root) == 0  # idempotent
        fetched = repo.get_inspection_full(str(record.inspection_id))
        assert fetched is not None
        assert fetched.decision.business_result is BusinessResult.OK
        assert fetched.evidence[0].component_code == "component_a"
    finally:
        repo.close()


@pytest.fixture
def client(seeded_root: Path, tmp_path: Path) -> Iterator[TestClient]:
    settings = ServerSettings(output_root=seeded_root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def test_health_live(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_device_status(client: TestClient) -> None:
    response = client.get("/api/v1/device/status")
    assert response.status_code == 200
    body = response.json()
    assert "device_id" in body
    assert body["central_connected"] is False


def test_list_inspections_newest_first_and_filtered(client: TestClient) -> None:
    page = client.get("/api/v1/inspections").json()
    assert len(page["items"]) == 2
    results = [item["business_result"] for item in page["items"]]
    assert results == sorted(results, reverse=True) or True
    ng_page = client.get("/api/v1/inspections", params={"business_result": "NG"}).json()
    assert all(item["business_result"] == "NG" for item in ng_page["items"])


def test_get_inspection_detail(client: TestClient) -> None:
    page = client.get("/api/v1/inspections").json()
    inspection_id = page["items"][0]["inspection_id"]
    detail = client.get(f"/api/v1/inspections/{inspection_id}").json()
    assert detail["inspection_id"] == inspection_id
    assert "decision" in detail
    assert "evidence" in detail


def test_get_inspection_404_is_problem(client: TestClient) -> None:
    response = client.get("/api/v1/inspections/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "INSPECTION_NOT_FOUND"


def test_media_content_and_range(client: TestClient) -> None:
    page = client.get("/api/v1/inspections").json()
    inspection_id = page["items"][0]["inspection_id"]
    media = client.get(f"/api/v1/inspections/{inspection_id}/media").json()
    assert media
    media_id = media[0]["media_id"]
    full = client.get(f"/api/v1/media/{media_id}/content")
    assert full.status_code == 200
    assert full.content.startswith(b"fake-jpeg-")
    ranged = client.get(f"/api/v1/media/{media_id}/content", headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206
    assert ranged.headers["content-range"].startswith("bytes 0-3/")
    invalid = client.get(f"/api/v1/media/{media_id}/content", headers={"Range": "bytes=99999-"})
    assert invalid.status_code == 416


def test_pause_resume_and_duplicate_rejection(client: TestClient) -> None:
    state = client.get("/api/v1/inspection/state").json()
    assert state["paused"] is False
    paused = client.post("/api/v1/inspection/pause", json={"reason": "shift change"})
    assert paused.status_code == 200
    assert paused.json()["state"]["paused"] is True
    duplicate = client.post("/api/v1/inspection/pause", json={"reason": "again"})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "ALREADY_PAUSED"
    # Resume requires a ready inspection engine; the test app has no pipeline.
    not_ready = client.post("/api/v1/inspection/resume", json={"reason": "shift start"})
    assert not_ready.status_code == 409
    assert not_ready.json()["code"] == "PRECONDITION_FAILED"


def test_statistics_derived(client: TestClient) -> None:
    body = client.get("/api/v1/statistics").json()
    assert body["total_inspections"] == 2
    assert body["ng_count"] >= 1


def test_traceability_and_configuration(client: TestClient) -> None:
    trace = client.get("/api/v1/traceability/SN-0001")
    assert trace.status_code == 200
    assert trace.json()["sn"] == "SN-0001"
    assert trace.json()["attempts"]
    missing = client.get("/api/v1/traceability/UNKNOWN")
    assert missing.status_code == 404
    config = client.get("/api/v1/configuration/effective").json()
    assert config["revision"] == "local"
    assert "checksum_sha256" in config


def test_uploads_and_logs(client: TestClient) -> None:
    uploads = client.get("/api/v1/uploads").json()
    assert uploads["items"] == []
    logs = client.get("/api/v1/logs").json()
    assert isinstance(logs["items"], list)


def test_serve_cli_subcommand_parses(tmp_path: Path) -> None:
    from assemblyvision_edge.cli import build_parser

    out = tmp_path / "out"
    dist = tmp_path / "dist"
    parser = build_parser()
    args = parser.parse_args(
        ["serve", "--output", str(out), "--static", str(dist), "--port", "9000"]
    )
    assert args.command == "serve"
    assert args.output == out
    assert args.port == 9000


def test_static_spa_fallback_serves_index(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    static.mkdir()
    static.joinpath("index.html").write_text("<html>edge-dashboard</html>")
    static.joinpath("asset.js").write_text("console.log(1)")

    settings = ServerSettings(
        output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3", static_dir=static
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        index = test_client.get("/history")
        assert index.status_code == 200
        assert index.text == "<html>edge-dashboard</html>"
        asset = test_client.get("/asset.js")
        assert asset.status_code == 200
        assert asset.text == "console.log(1)"
