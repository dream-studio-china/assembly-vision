"""C4 review API tests over the full FastAPI path.

Exercises the review queue, append submission with Idempotency-Key and
If-Match headers, stale-revision 409, disposition policy 422, unknown
inspection 404, and the detail response carrying the latest review.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
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
def client(repository: CentralRepository) -> Iterator[TestClient]:
    run_bootstrap(
        repository,
        resolve_plan(
            _settings(),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    )
    with TestClient(_app(repository)) as test_client:
        yield test_client


def _settings(**overrides: object) -> CentralSettings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        "admin_session_ttl_minutes": 60,
        "secure_cookies": False,
    }
    values.update(overrides)
    return CentralSettings(**values)  # type: ignore[arg-type]


def _app(repository: CentralRepository) -> FastAPI:
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
        storage=NoopObjectStorage(),
    )


def _admin_headers(**extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_ADMIN_TOKEN}", **extra}


def _device_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_DEVICE_TOKEN}"}


def _seed(
    repository: CentralRepository,
    *,
    ng_count: int = 1,
    ok_count: int = 1,
) -> tuple[list[str], list[str]]:
    """Seed NG and OK inspections; returns (ng_ids, ok_ids)."""
    result = run_bootstrap(
        repository,
        resolve_plan(
            _settings(),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    ).result
    device = repository.get_device(result.organization_id, result.device_row_id)
    assert device is not None
    ng_ids: list[str] = []
    ok_ids: list[str] = []
    sequence = 1
    for _ in range(ng_count):
        record = build_record(
            device_id=_DEVICE_ID,
            device_sequence=sequence,
            business=BusinessResult.NG,
        )
        repository.ingest_inspection(
            device=device,
            idempotency_key=f"inspection:{record.device_id}:{record.inspection_id}",
            request_hash=content_hash(record),
            object_id=str(record.inspection_id),
            inspection_id=str(record.inspection_id),
            record=record,
            payload_json=canonical_payload(record).decode("utf-8"),
            received_at=datetime.now(UTC),
        )
        ng_ids.append(str(record.inspection_id))
        sequence += 1
    for _ in range(ok_count):
        record = build_record(
            device_id=_DEVICE_ID,
            device_sequence=sequence,
            business=BusinessResult.OK,
        )
        repository.ingest_inspection(
            device=device,
            idempotency_key=f"inspection:{record.device_id}:{record.inspection_id}",
            request_hash=content_hash(record),
            object_id=str(record.inspection_id),
            inspection_id=str(record.inspection_id),
            record=record,
            payload_json=canonical_payload(record).decode("utf-8"),
            received_at=datetime.now(UTC),
        )
        ok_ids.append(str(record.inspection_id))
        sequence += 1
    return ng_ids, ok_ids


def test_reviews_require_admin(client: TestClient) -> None:
    assert client.get("/api/v1/reviews/queue", headers=_device_headers()).status_code == 401


def test_review_queue_lists_unreviewed_ng(
    repository: CentralRepository, client: TestClient
) -> None:
    ng_ids, ok_ids = _seed(repository, ng_count=2, ok_count=1)
    response = client.get("/api/v1/reviews/queue", headers=_admin_headers())
    assert response.status_code == 200
    body = response.json()
    assert {item["inspection_id"] for item in body["items"]} == set(ng_ids)
    assert all(item["business_result"] == "NG" for item in body["items"])
    assert ok_ids[0] not in {item["inspection_id"] for item in body["items"]}
    assert body["items"][0]["reason_codes"] == ["COMPONENT_MISSING:component_a"]


def test_submit_review_appends_and_replays(
    repository: CentralRepository, client: TestClient
) -> None:
    ng_ids, _ = _seed(repository)
    inspection_id = ng_ids[0]
    payload = {"disposition": "CONFIRMED_NG", "reason": "verified missing"}
    first = client.post(
        f"/api/v1/inspections/{inspection_id}/reviews",
        json=payload,
        headers=_admin_headers(**{"Idempotency-Key": "review-1"}),
    )
    assert first.status_code == 201
    assert first.json()["revision"] == 1
    assert first.json()["original_business_result"] == "NG"
    # Identical retry returns the original record (200).
    replay = client.post(
        f"/api/v1/inspections/{inspection_id}/reviews",
        json=payload,
        headers=_admin_headers(**{"Idempotency-Key": "review-1"}),
    )
    assert replay.status_code == 200
    assert replay.json()["revision"] == 1
    # History lists the append.
    history = client.get(f"/api/v1/inspections/{inspection_id}/reviews", headers=_admin_headers())
    assert len(history.json()) == 1


def test_submit_review_stale_if_match_conflicts(
    repository: CentralRepository, client: TestClient
) -> None:
    ng_ids, _ = _seed(repository)
    inspection_id = ng_ids[0]
    first = client.post(
        f"/api/v1/inspections/{inspection_id}/reviews",
        json={"disposition": "CONFIRMED_NG"},
        headers=_admin_headers(**{"Idempotency-Key": "r1", "If-Match": "0"}),
    )
    assert first.status_code == 201
    stale = client.post(
        f"/api/v1/inspections/{inspection_id}/reviews",
        json={"disposition": "CONFIRMED_NG"},
        headers=_admin_headers(**{"Idempotency-Key": "r2", "If-Match": "0"}),
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "REVIEW_CONFLICT"
    # The first review is untouched.
    history = client.get(f"/api/v1/inspections/{inspection_id}/reviews", headers=_admin_headers())
    assert [r["revision"] for r in history.json()] == [1]


def test_submit_review_requires_idempotency_key(
    repository: CentralRepository, client: TestClient
) -> None:
    ng_ids, _ = _seed(repository)
    response = client.post(
        f"/api/v1/inspections/{ng_ids[0]}/reviews",
        json={"disposition": "CONFIRMED_NG"},
        headers=_admin_headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_submit_review_disposition_policy_rejected(
    repository: CentralRepository, client: TestClient
) -> None:
    ng_ids, _ = _seed(repository)
    response = client.post(
        f"/api/v1/inspections/{ng_ids[0]}/reviews",
        json={"disposition": "CORRECTED_NG"},
        headers=_admin_headers(**{"Idempotency-Key": "r1"}),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REVIEW_DISPOSITION_INVALID"


def test_submit_review_unknown_inspection_404(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/inspections/{uuid4()}/reviews",
        json={"disposition": "CONFIRMED_NG"},
        headers=_admin_headers(**{"Idempotency-Key": "r1"}),
    )
    assert response.status_code == 404


def test_detail_carries_latest_review(repository: CentralRepository, client: TestClient) -> None:
    ng_ids, _ = _seed(repository)
    inspection_id = ng_ids[0]
    client.post(
        f"/api/v1/inspections/{inspection_id}/reviews",
        json={"disposition": "CONFIRMED_OK", "reason": "operator override"},
        headers=_admin_headers(**{"Idempotency-Key": "r1"}),
    )
    detail = client.get(f"/api/v1/inspections/{inspection_id}", headers=_admin_headers())
    assert detail.status_code == 200
    latest = detail.json()["latest_review"]
    assert latest is not None
    assert latest["disposition"] == "CONFIRMED_OK"
    assert latest["revision"] == 1
    # The machine outcome is byte-for-byte unchanged.
    assert detail.json()["business_result"] == "NG"
    assert detail.json()["internal_decision"] == "NG"
    # An unreviewed inspection has no latest review.
    listing = client.get("/api/v1/inspections", headers=_admin_headers())
    unreviewed = [i for i in listing.json()["items"] if i["business_result"] == "OK"][0]
    detail_ok = client.get(
        f"/api/v1/inspections/{unreviewed['inspection_id']}", headers=_admin_headers()
    )
    assert detail_ok.json()["latest_review"] is None
