"""Tests for the confidence-drift endpoint and aggregation (design 15.3.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

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
    ProductResolution,
)
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings
from fastapi.testclient import TestClient

FIXED_NOW = datetime(2026, 6, 10, 10, 0, tzinfo=UTC)
RULE_VERSION_ID = str(uuid4())
PRODUCT_MODEL_VERSION_ID = uuid4()
COMPONENT_MODEL_VERSION_ID = uuid4()
AGGREGATION_POLICY_VERSION = "single-frame-mvp-1"


def _write_record(
    root: Path,
    completed_at: datetime,
    evidence: list[tuple[str, float | None, int]],
    *,
    product_code: str = "model_a",
    rule_version_id: str = RULE_VERSION_ID,
    product_model_version_id: UUID = PRODUCT_MODEL_VERSION_ID,
    component_model_version_id: UUID = COMPONENT_MODEL_VERSION_ID,
    aggregation_policy_version: str = AGGREGATION_POLICY_VERSION,
) -> None:
    """Write one inspection.json bundle with the given component evidence.

    Each evidence tuple is (component_code, best_confidence, detection_count);
    a None confidence models a MISSING component that contributes no
    confidence evidence.
    """
    record = InspectionRecord(
        inspection_id=uuid4(),
        device_id=uuid4(),
        device_sequence=1,
        lifecycle_status=InspectionLifecycle.COMPLETED,
        started_at=completed_at,
        completed_at=completed_at,
        barcode_result=BarcodeResult(status="NOT_REQUIRED", value=None),
        product_resolution=ProductResolution(
            status="RESOLVED", source="CONFIGURED_DEFAULT", product_code=product_code
        ),
        frame_quality_summary=FrameQualitySummary(
            total_frame_count=1, usable_frame_count=1, rejected_frame_count=0
        ),
        application_version="0.1.0",
        product_model_version_id=product_model_version_id,
        product_model_checksum_sha256="0" * 64,
        component_model_version_id=component_model_version_id,
        component_model_checksum_sha256="0" * 64,
        rule_version_id=UUID(rule_version_id),
        aggregation_policy_version=aggregation_policy_version,
        evidence=[
            AggregatedComponentEvidence(
                component_code=code,
                state="PRESENT" if confidence is not None else "MISSING",
                best_confidence=confidence,
                usable_frame_count=max(detections, 1),
                detection_count=detections,
                adjacent_detection_run=detections,
                supporting_frame_ids=[uuid4()] if confidence is not None else [],
                policy_reason_codes=[] if confidence is not None else [f"MISSING:{code}"],
                box_area_ratios=[0.5] if confidence is not None else [],
                box_centers=[(0.5, 0.5)] if confidence is not None else [],
            )
            for code, confidence, detections in evidence
        ],
        decision=InspectionDecision(
            internal_decision=InternalDecision.OK,
            business_result=BusinessResult.OK,
            missing_components=[],
            reason_codes=[],
            decided_at=completed_at,
        ),
        synchronization_status="LOCAL_ONLY",
        processing_ms=12,
    )
    directory = root / str(record.inspection_id)
    directory.mkdir(parents=True)
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))


def _seed(root: Path) -> None:
    """Seed a falling-confidence scenario for model_a + RULE_VERSION_ID.

    Today: component_a 0.90 (10 frames) and component_b 0.80 (5 frames).
    Yesterday: component_a 0.95. Previous 7 days: component_a 0.94 and 0.96.
    Previous 30 days (outside the 7-day window): component_a 0.93.
    """
    _write_record(
        root,
        datetime(2026, 6, 10, 8, 0, tzinfo=UTC),
        [("component_a", 0.90, 10), ("component_b", 0.80, 5)],
    )
    _write_record(
        root,
        datetime(2026, 6, 9, 8, 0, tzinfo=UTC),
        [("component_a", 0.95, 10)],
    )
    _write_record(
        root,
        datetime(2026, 6, 8, 8, 0, tzinfo=UTC),
        [("component_a", 0.94, 10)],
    )
    _write_record(
        root,
        datetime(2026, 6, 4, 8, 0, tzinfo=UTC),
        [("component_a", 0.96, 10)],
    )
    _write_record(
        root,
        datetime(2026, 5, 21, 8, 0, tzinfo=UTC),
        [("component_a", 0.93, 10)],
    )


def _make_client(root: Path, tmp_path: Path) -> TestClient:
    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    app.state.clock = lambda: FIXED_NOW
    return TestClient(app)


def _drift(
    client: TestClient,
    *,
    product_code: str | None = "model_a",
    rule_version_id: str | None = RULE_VERSION_ID,
    **params: Any,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "product_code": product_code,
        "rule_version_id": rule_version_id,
        "product_model_version_id": str(PRODUCT_MODEL_VERSION_ID),
        "component_model_version_id": str(COMPONENT_MODEL_VERSION_ID),
        "aggregation_policy_version": AGGREGATION_POLICY_VERSION,
    }
    query.update(params)
    response = client.get("/api/v1/statistics/confidence-drift", params=query)
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def test_confidence_drift_weighted_means_and_deltas(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    _seed(root)
    with _make_client(root, tmp_path) as client:
        body = _drift(client)

    today = body["periods"]["today"]
    # (0.90*10 + 0.80*5) / 15
    assert today["weighted_mean"] == pytest.approx(13.0 / 15.0)
    assert today["median"] == pytest.approx(0.85)
    assert today["inspection_count"] == 1
    assert today["evidence_count"] == 2

    yesterday = body["periods"]["yesterday"]
    assert yesterday["weighted_mean"] == pytest.approx(0.95)

    previous_7d = body["periods"]["previous_7d"]
    # (0.94*10 + 0.96*10 + 0.95*10) / 30; the window includes yesterday.
    assert previous_7d["weighted_mean"] == pytest.approx(0.95)
    assert previous_7d["inspection_count"] == 3

    previous_30d = body["periods"]["previous_30d"]
    # (0.94 + 0.96 + 0.95 + 0.93) * 10 / 40; the 30-day window also includes
    # the 2026-05-21 record outside the 7-day window.
    assert previous_30d["weighted_mean"] == pytest.approx(37.8 / 40.0)
    assert previous_30d["inspection_count"] == 4

    vs_7d = body["comparison"]["today_vs_previous_7d"]
    assert vs_7d["weighted_mean_delta"] == pytest.approx(13.0 / 15.0 - 0.95)
    assert vs_7d["weighted_mean_relative_percent"] == pytest.approx(
        (13.0 / 15.0 - 0.95) / 0.95 * 100.0
    )
    assert vs_7d["today_evidence_count"] == 2
    assert vs_7d["baseline_evidence_count"] == 3

    vs_30d = body["comparison"]["today_vs_previous_30d"]
    assert vs_30d["weighted_mean_delta"] == pytest.approx(13.0 / 15.0 - 37.8 / 40.0)
    assert vs_30d["baseline_evidence_count"] == 4

    assessment = body["assessment"]
    assert assessment["level"] == "noticeable_drop"
    assert "previous-7-day" in assessment["detail"]

    # Only today-observed components are listed; the largest drop first.
    components = body["components"]
    assert [c["component_code"] for c in components] == ["component_a", "component_b"]
    assert components[0]["delta"] == pytest.approx(0.90 - 0.95)
    assert components[0]["baseline_weighted_mean"] == pytest.approx(0.95)
    assert components[1]["baseline_weighted_mean"] is None
    assert components[1]["delta"] is None

    scope = body["scope"]
    assert scope["product_code"] == "model_a"
    assert scope["rule_version_id"] == RULE_VERSION_ID
    assert scope["product_model_version_id"] == str(PRODUCT_MODEL_VERSION_ID)
    assert scope["component_model_version_id"] == str(COMPONENT_MODEL_VERSION_ID)
    assert scope["aggregation_policy_version"] == AGGREGATION_POLICY_VERSION
    assert scope["tz_offset_minutes"] == 0
    assert scope["as_of_iso"] == FIXED_NOW.isoformat()


def test_confidence_drift_isolation_across_product_and_rule(tmp_path: Path) -> None:
    """Other products and rules never leak into the same-product report."""
    root = tmp_path / "out"
    root.mkdir()
    _seed(root)
    _write_record(
        root,
        datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        [("component_a", 0.50, 10)],
        product_code="model_b",
    )
    _write_record(
        root,
        datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        [("component_a", 0.40, 10)],
        rule_version_id=str(uuid4()),
    )
    _write_record(
        root,
        datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        [("component_a", 0.30, 10)],
        component_model_version_id=uuid4(),
    )
    _write_record(
        root,
        datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        [("component_a", 0.20, 10)],
        aggregation_policy_version="temporal-v2",
    )
    with _make_client(root, tmp_path) as client:
        # Filtered report is unaffected by the foreign records.
        body = _drift(client)
        today = body["periods"]["today"]
        assert today["evidence_count"] == 2
        assert today["weighted_mean"] == pytest.approx(13.0 / 15.0)
        # An incomplete scope cannot mix product, rule, model, or policy versions.
        incomplete = client.get("/api/v1/statistics/confidence-drift")
        assert incomplete.status_code == 422
        assert incomplete.headers["content-type"].startswith("application/problem+json")


def test_confidence_drift_stable(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    _write_record(
        root,
        datetime(2026, 6, 10, 8, 0, tzinfo=UTC),
        [("component_a", 0.95, 10)],
    )
    _write_record(
        root,
        datetime(2026, 6, 9, 8, 0, tzinfo=UTC),
        [("component_a", 0.95, 10)],
    )
    _write_record(
        root,
        datetime(2026, 6, 6, 8, 0, tzinfo=UTC),
        [("component_a", 0.95, 10)],
    )
    with _make_client(root, tmp_path) as client:
        body = _drift(client)
    assert body["assessment"]["level"] == "stable"


def test_confidence_drift_insufficient_data(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    with _make_client(root, tmp_path) as client:
        body = _drift(client)
    assert body["assessment"]["level"] == "insufficient_data"
    assert body["periods"]["today"]["weighted_mean"] is None
    assert body["periods"]["previous_7d"]["weighted_mean"] is None


def test_confidence_drift_component_filter(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    _seed(root)
    with _make_client(root, tmp_path) as client:
        body = _drift(client, component_code="component_b")
    today = body["periods"]["today"]
    assert today["evidence_count"] == 1
    assert today["weighted_mean"] == pytest.approx(0.80)
    assert [c["component_code"] for c in body["components"]] == ["component_b"]


def test_confidence_drift_rejects_invalid_tz_offset(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    with _make_client(root, tmp_path) as client:
        for offset in (1000, -1000):
            response = client.get(
                "/api/v1/statistics/confidence-drift", params={"tz_offset_minutes": offset}
            )
            assert response.status_code == 422


def test_confidence_drift_local_day_boundary(tmp_path: Path) -> None:
    """A UTC+8 deployment sees a 20:00Z record as today, UTC sees yesterday."""
    root = tmp_path / "out"
    root.mkdir()
    _seed(root)
    _write_record(
        root,
        datetime(2026, 6, 9, 20, 0, tzinfo=UTC),
        [("component_a", 0.88, 10)],
    )
    with _make_client(root, tmp_path) as client:
        body = _drift(client, tz_offset_minutes=480)
        assert body["periods"]["today"]["evidence_count"] == 3
        body_utc = _drift(client)
        assert body_utc["periods"]["yesterday"]["evidence_count"] == 2
        assert body_utc["periods"]["today"]["evidence_count"] == 2


def test_confidence_drift_window_half_open_boundary(tmp_path: Path) -> None:
    """Buckets are half-open [from, to): a record at today's midnight is today."""
    root = tmp_path / "out"
    root.mkdir()
    _seed(root)
    _write_record(
        root,
        datetime(2026, 6, 10, 0, 0, tzinfo=UTC),
        [("component_a", 0.70, 10)],
    )
    with _make_client(root, tmp_path) as client:
        body = _drift(client)
    assert body["periods"]["yesterday"]["evidence_count"] == 1
    assert body["periods"]["today"]["evidence_count"] == 3


def test_confidence_drift_record_at_now(tmp_path: Path) -> None:
    """A record completed at the injected clock instant is inside today."""
    root = tmp_path / "out"
    root.mkdir()
    _seed(root)
    _write_record(
        root,
        FIXED_NOW - timedelta(minutes=1),
        [("component_a", 0.99, 10)],
    )
    with _make_client(root, tmp_path) as client:
        body = _drift(client)
    assert body["periods"]["today"]["inspection_count"] == 2


def test_confidence_drift_excludes_zero_detection_confidence(tmp_path: Path) -> None:
    """A zero-detection row cannot fabricate a positive metric weight."""
    root = tmp_path / "out"
    root.mkdir()
    _write_record(
        root,
        datetime(2026, 6, 10, 8, 0, tzinfo=UTC),
        [("component_a", 0.10, 0), ("component_b", 0.90, 1)],
    )
    with _make_client(root, tmp_path) as client:
        body = _drift(client)
    today = body["periods"]["today"]
    assert today["weighted_mean"] == pytest.approx(0.90)
    assert today["evidence_count"] == 1
    assert [component["component_code"] for component in body["components"]] == ["component_b"]


def test_confidence_drift_normalizes_an_aware_clock_to_utc(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    _seed(root)
    with _make_client(root, tmp_path) as client:
        cast(Any, client.app).state.clock = lambda: FIXED_NOW.astimezone(
            timezone(timedelta(hours=8))
        )
        body = _drift(client)
    assert body["scope"]["as_of_iso"] == FIXED_NOW.isoformat()
    assert body["periods"]["today"]["evidence_count"] == 2
