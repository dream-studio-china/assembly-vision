"""C3 inspection/dashboard API tests over the full FastAPI path.

Seeds inspections through the repository and asserts organization scoping,
keyset cursors (valid, invalid, filter-mismatched), bounded filters, media
URL authorization, and dashboard aggregates through the real routers.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from assemblyvision_domain.models import BusinessResult
from central_service.api.app import create_app
from central_service.api.readiness import ReadinessCheck, ReadinessResult
from central_service.api.settings import CentralSettings
from central_service.persistence.bootstrap import resolve_plan, run_bootstrap
from central_service.persistence.repository import CentralRepository
from central_service.persistence.schema import metadata
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ingest_fixtures import (
    NoopObjectStorage,
    build_record,
    canonical_payload,
    content_hash,
)
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()


@pytest.fixture
def repository() -> Iterator[CentralRepository]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    try:
        yield CentralRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def storage() -> NoopObjectStorage:
    return NoopObjectStorage()


@pytest.fixture
def client(repository: CentralRepository, storage: NoopObjectStorage) -> Iterator[TestClient]:
    run_bootstrap(
        repository,
        resolve_plan(
            _settings(),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    )
    with TestClient(_app(repository, storage)) as test_client:
        yield test_client


def _settings(**overrides: object) -> CentralSettings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        "admin_session_ttl_minutes": 60,
        "secure_cookies": False,
    }
    values.update(overrides)
    return CentralSettings(**values)  # type: ignore[arg-type]


def _app(repository: CentralRepository, storage: NoopObjectStorage) -> FastAPI:
    readiness = ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=True, detail="ok"),
            ReadinessCheck(name="object_store", ok=True, detail="ok"),
            ReadinessCheck(name="credentials", ok=True, detail="ok"),
        )
    )
    return create_app(
        _settings(),
        readiness=lambda: readiness,
        repository=repository,
        storage=storage,
    )


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_ADMIN_TOKEN}"}


def _device_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_DEVICE_TOKEN}"}


def _seed(
    repository: CentralRepository,
    device_row_id: int,
    organization_id: int,
    storage: NoopObjectStorage,
) -> None:
    """Three inspections across days/outcomes; the second carries media."""
    day1 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    day2 = datetime(2026, 8, 2, 11, 0, tzinfo=UTC)
    media_bytes = b"fake-jpeg-bytes"
    specs = [
        (1, BusinessResult.OK, "SN-0001", "model_a", day1, None),
        (2, BusinessResult.NG, "SN-0002", "model_b", day1, media_bytes),
        (3, BusinessResult.OK, "SN-0003", "model_a", day2, None),
    ]
    for sequence, business, barcode, product, completed_at, media in specs:
        record = build_record(
            device_id=_DEVICE_ID,
            device_sequence=sequence,
            business=business,
            barcode=barcode,
            product_code=product,
            completed_at=completed_at,
            media_content=media,
        )
        repository.ingest_inspection(
            device=_device_row(repository, device_row_id, organization_id),
            idempotency_key=f"inspection:{record.device_id}:{record.inspection_id}",
            request_hash=content_hash(record),
            object_id=str(record.inspection_id),
            inspection_id=str(record.inspection_id),
            record=record,
            payload_json=canonical_payload(record).decode("utf-8"),
            received_at=completed_at + timedelta(seconds=3),
        )
        if media is not None:
            _bind_media(repository, record, device_row_id, organization_id, completed_at, storage)


def _device_row(repository: CentralRepository, device_row_id: int, organization_id: int) -> Any:
    device = repository.get_device(organization_id, device_row_id)
    assert device is not None
    return device


def _bind_media(
    repository: CentralRepository,
    record: Any,
    device_row_id: int,
    organization_id: int,
    completed_at: datetime,
    storage: NoopObjectStorage,
) -> None:
    device = _device_row(repository, device_row_id, organization_id)
    lookup = repository.get_inspection_media_manifest(device.id, str(record.inspection_id))
    assert lookup is not None
    inspection_pk, capture_at, _ = lookup
    media = record.media[0]
    object_key = f"org/1/device/{_DEVICE_ID}/2026/08/{media.media_id}"
    storage.put_object(object_key, b"fake-jpeg-bytes", media.mime_type)
    repository.persist_media(
        device=device,
        inspection_row_id=inspection_pk,
        idempotency_key=f"media:{record.device_id}:{media.media_id}",
        request_hash=media.checksum_sha256,
        object_id=str(media.media_id),
        inspection_id=str(record.inspection_id),
        central_object_id=str(uuid4()),
        object_key=object_key,
        media_kind=media.kind,
        mime_type=media.mime_type,
        size_bytes=media.size_bytes,
        checksum_sha256=media.checksum_sha256,
        capture_at=capture_at,
        received_at=completed_at + timedelta(seconds=3),
    )


def _bootstrap(repository: CentralRepository, storage: NoopObjectStorage) -> dict[str, int]:
    result = run_bootstrap(
        repository,
        resolve_plan(
            _settings(),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    ).result
    _seed(repository, result.device_row_id, result.organization_id, storage)
    return {
        "organization_id": result.organization_id,
        "device_row_id": result.device_row_id,
    }


def test_inspections_require_admin(client: TestClient) -> None:
    assert client.get("/api/v1/inspections").status_code == 401
    assert client.get("/api/v1/inspections", headers=_device_headers()).status_code == 401


def test_list_inspections_with_filters_and_pagination(
    repository: CentralRepository, client: TestClient, storage: NoopObjectStorage
) -> None:
    _bootstrap(repository, storage)
    response = client.get("/api/v1/inspections", headers=_admin_headers())
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["business_result"] == "OK"  # newest first
    ok = client.get("/api/v1/inspections?business_result=NG", headers=_admin_headers())
    assert [i["device_sequence"] for i in ok.json()["items"]] == [2]
    barcode = client.get("/api/v1/inspections?barcode=SN-0002", headers=_admin_headers())
    assert len(barcode.json()["items"]) == 1
    paged = client.get("/api/v1/inspections?limit=2", headers=_admin_headers())
    assert len(paged.json()["items"]) == 2
    assert paged.json()["next_cursor"]
    next_page = client.get(
        f"/api/v1/inspections?limit=2&cursor={paged.json()['next_cursor']}",
        headers=_admin_headers(),
    )
    assert next_page.status_code == 200
    assert len(next_page.json()["items"]) == 1


def test_list_inspections_rejects_mismatched_cursor(
    client: TestClient,
) -> None:
    bogus = base64.urlsafe_b64encode(
        json.dumps({"f": "deadbeef", "c": "2026-08-01T00:00:00+00:00", "i": 1}).encode()
    ).decode()
    response = client.get(f"/api/v1/inspections?cursor={bogus}", headers=_admin_headers())
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CURSOR"
    garbage = client.get("/api/v1/inspections?cursor=not-a-cursor", headers=_admin_headers())
    assert garbage.status_code == 400
    assert garbage.json()["code"] == "INVALID_CURSOR"


def test_inspection_detail_with_media_url(
    repository: CentralRepository, client: TestClient, storage: NoopObjectStorage
) -> None:
    _bootstrap(repository, storage)
    listing = client.get("/api/v1/inspections", headers=_admin_headers())
    inspection_id = listing.json()["items"][1]["inspection_id"]  # NG with media
    response = client.get(f"/api/v1/inspections/{inspection_id}", headers=_admin_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["business_result"] == "NG"
    assert body["missing_components"] == ["component_a"]
    assert len(body["components"]) == 1
    assert len(body["media"]) == 1
    media = body["media"][0]
    assert media["lifecycle"] == "AVAILABLE"
    assert media["url"] is not None
    assert media["url"] == "/api/v1/media/" + repository.list_media_bindings()[0].central_object_id
    assert body["receipt_status"] == "ACCEPTED"
    assert body["receipt_created_at"] is not None


def test_media_streaming_requires_admin_and_is_org_scoped(
    repository: CentralRepository, client: TestClient, storage: NoopObjectStorage
) -> None:
    _bootstrap(repository, storage)
    binding = repository.list_media_bindings()[0]
    url = f"/api/v1/media/{binding.central_object_id}"
    assert client.get(url, headers=_device_headers()).status_code == 401
    stream = client.get(url, headers=_admin_headers())
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("image/jpeg")
    assert stream.content == b"fake-jpeg-bytes"
    missing = client.get(f"/api/v1/media/{uuid4()}", headers=_admin_headers())
    assert missing.status_code == 404
    assert missing.json()["code"] == "MEDIA_NOT_FOUND"


def test_inspection_detail_unknown_returns_404(
    client: TestClient,
) -> None:
    response = client.get(f"/api/v1/inspections/{uuid4()}", headers=_admin_headers())
    assert response.status_code == 404
    assert response.json()["code"] == "INSPECTION_NOT_FOUND"


def test_invalid_uuids_fail_closed_not_500(client: TestClient) -> None:
    """Malformed UUIDs are typed 4xx problems, never internal errors."""
    detail = client.get("/api/v1/inspections/not-a-uuid", headers=_admin_headers())
    assert detail.status_code == 404
    assert detail.json()["code"] == "INSPECTION_NOT_FOUND"
    model_filter = client.get("/api/v1/inspections?model_version=abc", headers=_admin_headers())
    assert model_filter.status_code == 400
    assert model_filter.json()["code"] == "INVALID_FILTER"
    rule_filter = client.get("/api/v1/inspections?rule_version=abc", headers=_admin_headers())
    assert rule_filter.status_code == 400
    media = client.get("/api/v1/media/abc", headers=_admin_headers())
    assert media.status_code == 404
    assert media.json()["code"] == "MEDIA_NOT_FOUND"


def test_dashboard_summary_and_timeseries(
    repository: CentralRepository, client: TestClient, storage: NoopObjectStorage
) -> None:
    _bootstrap(repository, storage)
    summary = client.get("/api/v1/dashboard/summary", headers=_admin_headers())
    assert summary.status_code == 200
    body = summary.json()
    assert body["inspection_count"] == 3
    assert body["ok_count"] == 2
    assert body["ng_count"] == 1
    assert body["uncertain_count"] == 0
    timeseries = client.get("/api/v1/dashboard/timeseries", headers=_admin_headers())
    assert timeseries.status_code == 200
    points = timeseries.json()["points"]
    assert [p["bucket"] for p in points] == ["2026-08-01", "2026-08-02"]
    scoped = client.get("/api/v1/dashboard/summary?business_result=NG", headers=_admin_headers())
    assert scoped.json()["ng_count"] == 1
    assert scoped.json()["ok_count"] == 0


def test_dashboard_requires_admin(client: TestClient) -> None:
    assert client.get("/api/v1/dashboard/summary", headers=_device_headers()).status_code == 401


def test_dashboard_devices_last_seen(
    repository: CentralRepository, client: TestClient, storage: NoopObjectStorage
) -> None:
    _bootstrap(repository, storage)
    response = client.get("/api/v1/dashboard/devices", headers=_admin_headers())
    assert response.status_code == 200
    devices = response.json()
    assert len(devices) == 1
    assert devices[0]["device_id"] == str(_DEVICE_ID)
    assert devices[0]["inspection_count"] == 3
    assert devices[0]["last_seen_at"] is not None
