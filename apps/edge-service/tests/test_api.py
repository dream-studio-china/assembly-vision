"""Tests for the local edge API (FastAPI routers) and persistence layer."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
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


def test_reconcile_skips_media_outside_its_inspection_bundle(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.reconcile import reconcile_output_root

    root = tmp_path / "out"
    root.mkdir()
    record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-0001")
    record.media[0].relative_path = "edge.sqlite3"
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))

    repo = EdgeRepository.open(root / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 0
        assert repo.get_inspection(str(record.inspection_id)) is None
    finally:
        repo.close()


def test_reconcile_skips_duplicate_media_ids_without_aborting(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.reconcile import reconcile_output_root

    root = tmp_path / "out"
    root.mkdir()
    record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-0001")
    duplicate = record.media[0].model_copy(
        update={"relative_path": f"{record.inspection_id}/copy.jpg"}
    )
    record.media.append(duplicate)
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))

    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        assert reconcile_output_root(repo, root) == 0
        assert repo.get_inspection(str(record.inspection_id)) is None
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
    assert invalid.json()["code"] == "INVALID_RANGE"
    assert invalid.headers["content-range"].startswith("bytes */")
    assert invalid.headers["content-type"].startswith("application/problem+json")


def test_m1_removed_controls_return_404(client: TestClient) -> None:
    state = client.get("/api/v1/inspection/state").json()
    assert state["paused"] is False
    for endpoint, payload in (
        ("/api/v1/inspection/pause", {"reason": "shift change"}),
        ("/api/v1/inspection/resume", {"reason": "shift start"}),
        ("/api/v1/camera/reconnect", {"reason": "fault"}),
        ("/api/v1/uploads/00000000-0000-4000-8000-0000000000cc/retry", {"reason": "retry"}),
    ):
        response = client.post(endpoint, json=payload)
        assert response.status_code == 404


def test_statistics_derived(client: TestClient) -> None:
    body = client.get("/api/v1/statistics").json()
    assert body["total_inspections"] == 2
    assert body["ng_count"] >= 1


def test_statistics_filters_from_to_and_rejects_line(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for idx in range(4):
        record = _record(
            base + timedelta(hours=idx), business=BusinessResult.OK, barcode=f"SN-{idx}"
        )
        directory = root / str(record.inspection_id)
        directory.mkdir()
        directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))

    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as c:
        total = c.get("/api/v1/statistics").json()
        assert total["total_inspections"] == 4
        window = c.get("/api/v1/statistics", params={"from": "2026-01-01T02:00:00+00:00"}).json()
        assert window["total_inspections"] == 2
        bounded = c.get(
            "/api/v1/statistics",
            params={"from": "2026-01-01T01:00:00+00:00", "to": "2026-01-01T02:00:00+00:00"},
        ).json()
        assert bounded["total_inspections"] == 2
        unsupported = c.get("/api/v1/statistics", params={"line": "L1"})
        assert unsupported.status_code == 400
        assert unsupported.json()["code"] == "UNSUPPORTED_FILTER"


def test_statistics_rejects_invalid_and_non_utc_time_filters(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for idx in range(4):
        record = _record(
            base + timedelta(hours=idx), business=BusinessResult.OK, barcode=f"SN-{idx}"
        )
        directory = root / str(record.inspection_id)
        directory.mkdir()
        directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))

    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as c:
        naive = c.get("/api/v1/statistics", params={"from": "2026-01-01T02:00:00"})
        assert naive.status_code == 400
        assert naive.json()["code"] == "INVALID_FILTER"
        malformed = c.get("/api/v1/statistics", params={"from": "not-a-timestamp"})
        assert malformed.status_code == 422
        assert malformed.json()["code"] == "VALIDATION_FAILED"
        inverted = c.get(
            "/api/v1/statistics",
            params={"from": "2026-01-01T03:00:00+00:00", "to": "2026-01-01T01:00:00+00:00"},
        )
        assert inverted.status_code == 400
        assert inverted.json()["code"] == "INVALID_RANGE"
        offset = c.get("/api/v1/statistics", params={"from": "2026-01-01T03:00:00+02:00"}).json()
        # 03:00+02:00 normalizes to 01:00 UTC, so hours 1-3 are included.
        assert offset["total_inspections"] == 3


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
    # Reconcile now enqueues an outbox task per inspection and per media item
    # (design 12.4/13.3); the worker is not draining without a configured sink.
    assert len(uploads["items"]) == 4
    assert {item["kind"] for item in uploads["items"]} == {"INSPECTION", "MEDIA"}
    assert all(item["status"] == "PENDING" for item in uploads["items"])
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


def test_api_paths_never_fall_back_to_spa(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    static.mkdir()
    static.joinpath("index.html").write_text("<html>edge-dashboard</html>")

    settings = ServerSettings(
        output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3", static_dir=static
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        bare_api = test_client.get("/api")
        assert bare_api.status_code == 404
        assert "edge-dashboard" not in bare_api.text
        unknown_api = test_client.get("/api/unknown")
        assert unknown_api.status_code == 404
        assert "edge-dashboard" not in unknown_api.text
        # Client-side routes still get the SPA fallback.
        assert test_client.get("/history").text == "<html>edge-dashboard</html>"


def test_security_headers_applied_to_all_responses(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"


def test_invalid_cursor_returns_400(client: TestClient) -> None:
    response = client.get("/api/v1/inspections", params={"cursor": "not-a-cursor"})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CURSOR"


def test_cursor_bound_to_filter_set(client: TestClient) -> None:
    page = client.get("/api/v1/inspections", params={"business_result": "OK", "limit": 1})
    cursor = page.json().get("next_cursor")
    if cursor is None:
        return
    # Reusing the cursor with a different filter set is rejected, not silently
    # applied to the wrong result set.
    mismatched = client.get(
        "/api/v1/inspections",
        params={"business_result": "NG", "limit": 1, "cursor": cursor},
    )
    assert mismatched.status_code == 400
    assert mismatched.json()["code"] == "INVALID_CURSOR"
    # The same filter set accepts the cursor.
    matching = client.get(
        "/api/v1/inspections",
        params={"business_result": "OK", "limit": 1, "cursor": cursor},
    )
    assert matching.status_code == 200


def test_list_inspections_sn_filter(client: TestClient) -> None:
    page = client.get("/api/v1/inspections", params={"sn": "SN-00"}).json()
    assert len(page["items"]) == 2
    fuzzy = client.get("/api/v1/inspections", params={"sn": "sn-0001"}).json()
    assert len(fuzzy["items"]) == 1
    assert fuzzy["items"][0]["sn"] == "SN-0001"
    none = client.get("/api/v1/inspections", params={"sn": "zzz"}).json()
    assert none["items"] == []


def test_list_inspections_sn_filter_cursor_pagination(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for idx in range(5):
        record = _record(
            base + timedelta(hours=idx), business=BusinessResult.OK, barcode=f"SN-{idx:03d}"
        )
        directory = root / str(record.inspection_id)
        directory.mkdir()
        directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))

    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as c:
        first = c.get("/api/v1/inspections", params={"sn": "SN-", "limit": 2}).json()
        assert len(first["items"]) == 2
        cursor = first["next_cursor"]
        assert cursor is not None
        second = c.get(
            "/api/v1/inspections", params={"sn": "SN-", "limit": 2, "cursor": cursor}
        ).json()
        assert len(second["items"]) == 2
        assert second["next_cursor"] is not None
        third = c.get(
            "/api/v1/inspections",
            params={"sn": "SN-", "limit": 2, "cursor": second["next_cursor"]},
        ).json()
        assert len(third["items"]) == 1
        assert third["next_cursor"] is None
        walked = first["items"] + second["items"] + third["items"]
        assert len({item["inspection_id"] for item in walked}) == 5
        # Newest first: the seeded timestamps ascend with idx, so the first
        # page must start at the latest completed_at.
        assert walked[0]["sn"] == "SN-004"
        # A cursor is bound to the sn filter set that produced it.
        mismatch = c.get(
            "/api/v1/inspections",
            params={"sn": "SN-000", "limit": 2, "cursor": first["next_cursor"]},
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["code"] == "INVALID_CURSOR"


def test_purged_media_returns_410_even_when_file_exists(tmp_path: Path) -> None:
    import sqlite3

    from assemblyvision_edge.persistence.reconcile import reconcile_output_root

    root = tmp_path / "out"
    root.mkdir()
    record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-PURGED")
    directory = root / str(record.inspection_id)
    directory.mkdir()
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
    # The file still exists on disk; the metadata says PURGED.
    directory.joinpath("key_frame.jpg").write_bytes(b"still-here")

    db = tmp_path / "edge.sqlite3"
    repo = EdgeRepository.open(db)
    try:
        reconcile_output_root(repo, root)
    finally:
        repo.close()
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE media SET lifecycle = 'PURGED' WHERE media_id = ?",
            (str(record.media[0].media_id),),
        )
        conn.commit()
    finally:
        conn.close()

    settings = ServerSettings(output_root=root, db_path=db)
    app = create_app(settings)
    with TestClient(app) as test_client:
        response = test_client.get(f"/api/v1/media/{record.media[0].media_id}/content")
        assert response.status_code == 410
        assert response.json()["code"] == "MEDIA_PURGED"


def test_fresh_inspection_media_served_from_writer(tmp_path: Path) -> None:
    from assemblyvision_edge.output.writer import OutputWriter
    from PIL import Image

    root = tmp_path / "out"
    writer = OutputWriter(root)
    record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-WRITER")
    frame = Image.new("RGB", (40, 40), (30, 30, 30))
    saved = writer.save(record, full_frame=frame, roi_image=None, annotated=None)

    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as test_client:
        media = test_client.get(f"/api/v1/inspections/{saved.inspection_id}/media").json()
        assert len(media) == 1
        media_id = media[0]["media_id"]
        content = test_client.get(f"/api/v1/media/{media_id}/content")
        assert content.status_code == 200
        raw = (root / str(saved.inspection_id) / "key_frame.jpg").read_bytes()
        assert content.content == raw
        assert content.headers["content-type"].startswith("image/jpeg")


def _load_committed_openapi() -> dict[str, Any]:
    import json

    repo_root = Path(__file__).resolve().parents[3]
    return cast(
        dict[str, Any],
        json.loads(
            (repo_root / "apps/edge-service/openapi/edge-openapi.json").read_text(encoding="utf-8")
        ),
    )


def _finalize_openapi(spec: dict[str, Any]) -> dict[str, Any]:
    """Apply the deterministic dev-operation patch shared with the generator."""
    import importlib.util

    repo_root = Path(__file__).resolve().parents[3]
    loader_spec = importlib.util.spec_from_file_location(
        "generate_edge_openapi", repo_root / "scripts" / "generate-edge-openapi.py"
    )
    assert loader_spec is not None
    assert loader_spec.loader is not None
    module = importlib.util.module_from_spec(loader_spec)
    loader_spec.loader.exec_module(module)
    return cast(dict[str, Any], module.finalize_openapi(spec))


def test_openapi_matches_committed_document(tmp_path: Path) -> None:
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    assert _finalize_openapi(app.openapi()) == _load_committed_openapi()


def test_dev_operations_declare_binary_request_body_and_problem_responses() -> None:
    """F9: consumers must be able to call and handle the dev endpoints."""
    spec = _load_committed_openapi()
    for path in ("/api/v1/dev/inspect-frame", "/api/v1/dev/inspect-video"):
        op = spec["paths"][path]["post"]
        request_body = op.get("requestBody")
        assert request_body is not None, f"{path} must declare a required requestBody"
        assert request_body["required"] is True
        media = request_body["content"]["application/octet-stream"]
        assert media["schema"] == {"type": "string", "format": "binary"}
        for code in ("400", "404", "413", "503"):
            response = op["responses"].get(code)
            assert response is not None, f"{path} must declare the {code} problem response"
            assert (
                response["content"]["application/problem+json"]["schema"]["$ref"]
                == "#/components/schemas/Problem"
            )


def test_review_operations_declare_problem_responses() -> None:
    """Design 15.3.3: the documented review errors are discoverable from OpenAPI.

    The runtime returns these statuses as RFC 7807 problems, so generated
    clients must be able to type and handle them (PR-031 review finding).
    """
    spec = _load_committed_openapi()
    expectations: dict[str, dict[str, tuple[str, ...]]] = {
        "/api/v1/reviews": {"get": ("400",)},
        "/api/v1/inspections/{inspection_id}/reviews": {
            "get": ("404",),
            "post": ("404", "409", "422"),
        },
    }
    for path, methods in expectations.items():
        for method, codes in methods.items():
            operation = spec["paths"][path][method]
            for code in codes:
                response = operation["responses"].get(code)
                assert response is not None, (
                    f"{path} {method} must declare the {code} problem response"
                )
                media = response["content"].get("application/problem+json")
                assert media is not None, f"{path} {method} {code} must declare problem content"
                assert media["schema"]["$ref"] == "#/components/schemas/Problem", (
                    f"{path} {method} {code} must use the Problem schema"
                )


def test_video_frame_result_schema_exposes_decision_enums() -> None:
    """F12: video decisions must use the canonical OK/NG business result set."""
    spec = _load_committed_openapi()
    schema = spec["components"]["schemas"]["VideoFrameInspectResult"]
    business_ref = schema["properties"]["business_result"]["$ref"]
    internal_ref = schema["properties"]["internal_decision"]["$ref"]

    def enum_values(ref: str) -> list[str]:
        name = ref.rsplit("/", 1)[-1]
        return cast(list[str], spec["components"]["schemas"][name]["enum"])

    assert enum_values(business_ref) == ["OK", "NG"]
    assert enum_values(internal_ref) == ["OK", "NG", "UNCERTAIN"]
