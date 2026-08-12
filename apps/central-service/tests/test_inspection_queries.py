"""C3 history/dashboard repository query tests.

Seeds multiple inspections across days/outcomes/identities and exercises
organization scoping, keyset pagination, bounded filters, detail assembly,
and the dashboard aggregates on SQLite with foreign keys enforced.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from assemblyvision_domain.models import BusinessResult
from central_service.persistence.repository import (
    CentralRepository,
    InspectionFilter,
    PilotBootstrapResult,
)
from central_service.persistence.schema import metadata
from ingest_fixtures import build_record, canonical_payload, content_hash
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()


def _sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _enable_foreign_keys)
    metadata.create_all(engine)
    return engine


def _enable_foreign_keys(dbapi_connection: Any, connection_record: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
def repository() -> Iterator[CentralRepository]:
    engine = _sqlite_engine()
    try:
        yield CentralRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def device(repository: CentralRepository) -> PilotBootstrapResult:
    return repository.bootstrap_pilot(
        organization_name="Org A",
        site_name="Site A",
        line_name="Line A",
        device_id=str(_DEVICE_ID),
        device_name="Edge 1",
        device_upload_token=_DEVICE_TOKEN,
        admin_username="admin",
        admin_token=_ADMIN_TOKEN,
    )


def _ingest(repository: CentralRepository, device: PilotBootstrapResult, record: Any) -> None:
    device_row = repository.get_device(device.organization_id, device.device_row_id)
    assert device_row is not None
    repository.ingest_inspection(
        device=device_row,
        idempotency_key=f"inspection:{record.device_id}:{record.inspection_id}",
        request_hash=content_hash(record),
        object_id=str(record.inspection_id),
        inspection_id=str(record.inspection_id),
        record=record,
        payload_json=canonical_payload(record).decode("utf-8"),
        received_at=record.completed_at + timedelta(seconds=3),
    )


def _seed(repository: CentralRepository, device: PilotBootstrapResult) -> None:
    """Three inspections across two days and outcomes (Barcode A/B, model_a)."""
    day1 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    day2 = datetime(2026, 8, 2, 11, 0, tzinfo=UTC)
    specs = [
        (1, BusinessResult.OK, "SN-0001", "model_a", day1),
        (2, BusinessResult.NG, "SN-0002", "model_b", day1),
        (3, BusinessResult.OK, "SN-0003", "model_a", day2),
    ]
    for sequence, business, barcode, product, completed_at in specs:
        _ingest(
            repository,
            device,
            build_record(
                device_id=_DEVICE_ID,
                device_sequence=sequence,
                business=business,
                barcode=barcode,
                product_code=product,
                completed_at=completed_at,
            ),
        )


def test_list_inspections_is_organization_scoped_and_ordered(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    _seed(repository, device)
    items, has_more = repository.list_inspections(
        device.organization_id,
        InspectionFilter(),
        after_completed_at=None,
        after_id=None,
        limit=50,
    )
    assert has_more is False
    assert len(items) == 3
    # Newest completion first (day2 then day1, sequence 1 before 2 by id desc).
    assert [i.device_sequence for i in items] == [3, 2, 1]
    assert items[0].business_result == "OK"
    # Another organization sees nothing.
    other = repository.bootstrap_pilot(
        organization_name="Org B",
        site_name="Site B",
        line_name="Line B",
        device_id=str(uuid4()),
        device_name="Edge 2",
        device_upload_token=_DEVICE_TOKEN,
        admin_username="admin",
        admin_token=_ADMIN_TOKEN,
    )
    empty, _ = repository.list_inspections(
        other.organization_id, InspectionFilter(), after_completed_at=None, after_id=None, limit=50
    )
    assert empty == []


def test_list_inspections_keyset_pagination(repository: CentralRepository, device: Any) -> None:
    _seed(repository, device)
    first, has_more = repository.list_inspections(
        device.organization_id,
        InspectionFilter(),
        after_completed_at=None,
        after_id=None,
        limit=2,
    )
    assert has_more is True
    assert [i.device_sequence for i in first] == [3, 2]
    last = first[-1]
    second, has_more = repository.list_inspections(
        device.organization_id,
        InspectionFilter(),
        after_completed_at=last.completed_at,
        after_id=last.id,
        limit=2,
    )
    assert has_more is False
    assert [i.device_sequence for i in second] == [1]


def test_list_inspections_bounded_filters(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    _seed(repository, device)

    def _ids(filter_: InspectionFilter) -> list[int]:
        items, _ = repository.list_inspections(
            device.organization_id, filter_, after_completed_at=None, after_id=None, limit=50
        )
        return sorted(i.device_sequence for i in items)

    assert _ids(InspectionFilter(business_result="OK")) == [1, 3]
    assert _ids(InspectionFilter(business_result="NG")) == [2]
    assert _ids(InspectionFilter(barcode="SN-0002")) == [2]
    assert _ids(InspectionFilter(product_code="model_b")) == [2]
    assert _ids(InspectionFilter(reason_code="COMPONENT_MISSING:component_a")) == [2]
    assert _ids(InspectionFilter(from_at=datetime(2026, 8, 2, tzinfo=UTC))) == [3]
    assert _ids(
        InspectionFilter(
            from_at=datetime(2026, 8, 1, tzinfo=UTC),
            to_at=datetime(2026, 8, 2, tzinfo=UTC),
        )
    ) == [1, 2]


def test_list_inspections_rule_version_filter(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    _seed(repository, device)
    first = repository.list_inspections(
        device.organization_id, InspectionFilter(), after_completed_at=None, after_id=None, limit=1
    )[0][0]
    items, _ = repository.list_inspections(
        device.organization_id,
        InspectionFilter(rule_version_id=first.rule_version_id),
        after_completed_at=None,
        after_id=None,
        limit=50,
    )
    assert all(i.rule_version_id == first.rule_version_id for i in items)


def test_get_inspection_detail_assembles_evidence_and_media(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    media_bytes = b"fake-jpeg-bytes"
    record = build_record(
        device_id=_DEVICE_ID,
        device_sequence=1,
        business=BusinessResult.NG,
        media_content=media_bytes,
        completed_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    )
    _ingest(repository, device, record)
    # Bind the media (C2b) so the detail carries a binding row.
    device_row = repository.get_device(device.organization_id, device.device_row_id)
    assert device_row is not None
    lookup = repository.get_inspection_media_manifest(device_row.id, str(record.inspection_id))
    assert lookup is not None
    inspection_pk, capture_at, _ = lookup
    media = record.media[0]
    repository.persist_media(
        device=device_row,
        inspection_row_id=inspection_pk,
        idempotency_key=f"media:{record.device_id}:{media.media_id}",
        request_hash=media.checksum_sha256,
        object_id=str(media.media_id),
        inspection_id=str(record.inspection_id),
        central_object_id=str(uuid4()),
        object_key=f"org/1/device/{_DEVICE_ID}/2026/08/{media.media_id}",
        media_kind=media.kind,
        mime_type=media.mime_type,
        size_bytes=media.size_bytes,
        checksum_sha256=media.checksum_sha256,
        capture_at=capture_at,
        received_at=record.completed_at + timedelta(seconds=3),
    )
    detail = repository.get_inspection_detail(device.organization_id, str(record.inspection_id))
    assert detail is not None
    assert detail.summary.business_result == "NG"
    assert detail.summary.upload_delay_ms == 3000
    assert [c.component_code for c in detail.components] == ["component_a"]
    assert detail.components[0].state == "MISSING"
    assert len(detail.media) == 1
    assert detail.media[0].lifecycle == "AVAILABLE"
    assert detail.media[0].media_kind == "KEY_FRAME"
    assert detail.media[0].mime_type == "image/jpeg"
    # Cross-organization lookup returns nothing.
    assert (
        repository.get_inspection_detail(device.organization_id + 999, str(record.inspection_id))
        is None
    )


def test_dashboard_summary_counts_and_delay(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    _seed(repository, device)
    summary = repository.dashboard_summary(device.organization_id, InspectionFilter())
    assert summary.inspection_count == 3
    assert summary.ok_count == 2
    assert summary.ng_count == 1
    assert summary.uncertain_count == 0
    assert summary.avg_upload_delay_ms == pytest.approx(3000.0, abs=10)
    # Scope to one day.
    day2 = repository.dashboard_summary(
        device.organization_id,
        InspectionFilter(from_at=datetime(2026, 8, 2, tzinfo=UTC)),
    )
    assert day2.inspection_count == 1
    assert day2.ok_count == 1
    # Empty scope stays zero, never fabricated.
    empty = repository.dashboard_summary(
        device.organization_id,
        InspectionFilter(from_at=datetime(2030, 1, 1, tzinfo=UTC)),
    )
    assert empty.inspection_count == 0
    assert empty.ok_count == 0
    assert empty.avg_upload_delay_ms is None


def test_dashboard_timeseries_daily_buckets(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    _seed(repository, device)
    points = repository.dashboard_timeseries(device.organization_id, InspectionFilter())
    assert [p.bucket for p in points] == ["2026-08-01", "2026-08-02"]
    assert points[0].ng_count == 1
    assert points[0].ok_count == 1
    assert points[1].ok_count == 1
