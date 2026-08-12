"""C2a ingestion API tests over the full FastAPI path.

The application is built with an injected SQLite-backed repository so device
authentication, problem responses, idempotent replay, and payload conflicts
are exercised through the real router without PostgreSQL or MinIO.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
from assemblyvision_domain.models import BusinessResult, InspectionRecord
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
    build_envelope,
    build_media_envelope,
    build_record,
    canonical_payload,
)
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()

_INGEST_URL = "/api/v1/inspection-uploads"


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


def _app(
    repository: CentralRepository, settings_overrides: dict[str, object] | None = None
) -> FastAPI:
    readiness = ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=True, detail="ok"),
            ReadinessCheck(name="object_store", ok=True, detail="ok"),
            ReadinessCheck(name="credentials", ok=True, detail="ok"),
        )
    )
    settings = _settings(**(settings_overrides or {}))
    return create_app(
        settings,
        readiness=lambda: readiness,
        repository=repository,
        storage=NoopObjectStorage(),
    )


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_ADMIN_TOKEN}"}


def _device_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_DEVICE_TOKEN}"}


def _record(**overrides: object) -> InspectionRecord:
    values: dict[str, object] = {"device_id": _DEVICE_ID, "business": BusinessResult.NG}
    values.update(overrides)
    return build_record(**values)  # type: ignore[arg-type]


def test_ingest_requires_device_credential(client: TestClient) -> None:
    response = client.post(_INGEST_URL, content=b"{}")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_admin_credential_cannot_ingest(client: TestClient) -> None:
    response = client.post(_INGEST_URL, content=b"{}", headers=_admin_headers())
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_ingest_new_inspection_returns_verified_receipt(client: TestClient) -> None:
    record = _record()
    envelope = build_envelope(record)
    response = client.post(_INGEST_URL, content=envelope, headers=_device_headers())
    assert response.status_code == 201
    body = response.json()
    assert body["idempotency_key"] == f"inspection:{record.device_id}:{record.inspection_id}"
    assert body["object_id"] == str(record.inspection_id)
    assert body["kind"] == "INSPECTION"
    assert body["size_bytes"] == len(canonical_payload(record))
    assert body["checksum_sha256"]
    assert body["central_object_id"] is None


def test_ingest_identical_replay_returns_original_receipt(client: TestClient) -> None:
    record = _record()
    envelope = build_envelope(record)
    first = client.post(_INGEST_URL, content=envelope, headers=_device_headers())
    second = client.post(_INGEST_URL, content=envelope, headers=_device_headers())
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()


def test_ingest_payload_conflict_returns_409(client: TestClient) -> None:
    record = _record()
    first = client.post(_INGEST_URL, content=build_envelope(record), headers=_device_headers())
    assert first.status_code == 201
    changed = record.model_copy(update={"processing_ms": record.processing_ms + 1})
    conflict = client.post(_INGEST_URL, content=build_envelope(changed), headers=_device_headers())
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "PAYLOAD_CONFLICT"


def test_ingest_device_mismatch_returns_403(client: TestClient) -> None:
    record = build_record(device_id=uuid4(), business=BusinessResult.NG)
    response = client.post(_INGEST_URL, content=build_envelope(record), headers=_device_headers())
    assert response.status_code == 403
    assert response.json()["code"] == "DEVICE_MISMATCH"


def test_ingest_checksum_mismatch_returns_422(client: TestClient) -> None:
    record = _record()
    envelope = build_envelope(record, checksum_sha256="1" * 64)
    response = client.post(_INGEST_URL, content=envelope, headers=_device_headers())
    assert response.status_code == 422
    assert response.json()["code"] == "CHECKSUM_MISMATCH"


def test_ingest_unknown_envelope_fields_rejected(client: TestClient) -> None:
    record = _record()
    envelope = json.loads(build_envelope(record))
    envelope["sneaky"] = "extra"
    response = client.post(
        _INGEST_URL,
        content=json.dumps(envelope).encode("utf-8"),
        headers=_device_headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_ENVELOPE"


def test_ingest_malformed_payload_returns_422(client: TestClient) -> None:
    record = _record()
    envelope = json.loads(build_envelope(record))
    envelope["payload_b64"] = "not-base64!!"
    response = client.post(
        _INGEST_URL,
        content=json.dumps(envelope).encode("utf-8"),
        headers=_device_headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_PAYLOAD_ENCODING"


def test_ingest_oversized_body_returns_413(
    client: TestClient, repository: CentralRepository
) -> None:
    small: dict[str, object] = {
        "max_envelope_body_bytes": 1024,
        "max_inspection_payload_bytes": 1024,
    }
    run_bootstrap(
        repository,
        resolve_plan(
            _settings(**small),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    )
    with TestClient(_app(repository, small)) as small_client:
        big_body = b"x" * 2048
        response = small_client.post(_INGEST_URL, content=big_body, headers=_device_headers())
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_ingest_oversized_inspection_payload_returns_413(
    client: TestClient, repository: CentralRepository
) -> None:
    small: dict[str, object] = {"max_inspection_payload_bytes": 100}
    run_bootstrap(
        repository,
        resolve_plan(
            _settings(**small),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    )
    with TestClient(_app(repository, small)) as small_client:
        record = _record()
        envelope = build_envelope(record)
        response = small_client.post(_INGEST_URL, content=envelope, headers=_device_headers())
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_media_ingestion_returns_retryable_503(client: TestClient) -> None:
    record = _record()
    envelope = build_media_envelope(record, bytes_content=b"fake-jpeg-bytes")
    response = client.post(_INGEST_URL, content=envelope, headers=_device_headers())
    assert response.status_code == 503
    assert response.json()["code"] == "MEDIA_INGESTION_UNAVAILABLE"
    assert response.headers.get("Retry-After") == "5"


def test_ingest_rejects_wrong_content_kind_for_payload(client: TestClient) -> None:
    # An INSPECTION envelope whose payload cannot parse as an InspectionRecord
    # is a permanent typed failure, not an accepted resource.
    record = _record()
    payload = b"[]"
    envelope = json.loads(build_envelope(record))
    envelope["payload_b64"] = base64.b64encode(payload).decode("ascii")
    envelope["size_bytes"] = len(payload)
    envelope["checksum_sha256"] = hashlib.sha256(payload).hexdigest()
    response = client.post(
        _INGEST_URL,
        content=json.dumps(envelope).encode("utf-8"),
        headers=_device_headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_PAYLOAD"
