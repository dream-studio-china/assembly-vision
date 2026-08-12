"""C6 fault-tolerance tests: temporary dependency failures and rate limits.

Proves that a failed object store or database dependency yields a retryable
``503`` with ``Retry-After`` and never issues a false success receipt, and
that the per-client rate limiter returns ``429`` with a bounded hint while
health endpoints stay probeable.
"""

from __future__ import annotations

from collections.abc import Iterator
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
    build_envelope,
    build_media_envelope,
    build_record,
)
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()
_INGEST_URL = "/api/v1/inspection-uploads"


class FailingObjectStorage(NoopObjectStorage):
    """Object store stub whose writes always fail (temporary dependency outage)."""

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        raise RuntimeError("minio connection refused")


def _sqlite_engine() -> Any:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    return engine


@pytest.fixture
def repository() -> Iterator[CentralRepository]:
    engine = _sqlite_engine()
    try:
        yield CentralRepository(engine)
    finally:
        engine.dispose()


def _settings(**overrides: object) -> CentralSettings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        "admin_session_ttl_minutes": 60,
        "secure_cookies": False,
    }
    values.update(overrides)
    return CentralSettings(**values)  # type: ignore[arg-type]


def _app(
    repository: CentralRepository,
    storage: NoopObjectStorage | None = None,
    settings_overrides: dict[str, object] | None = None,
) -> FastAPI:
    readiness = ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=True, detail="ok"),
            ReadinessCheck(name="object_store", ok=True, detail="ok"),
            ReadinessCheck(name="credentials", ok=True, detail="ok"),
        )
    )
    return create_app(
        _settings(**(settings_overrides or {})),
        readiness=lambda: readiness,
        repository=repository,
        storage=storage or NoopObjectStorage(),
    )


def _client(
    repository: CentralRepository,
    *,
    storage: NoopObjectStorage | None = None,
    settings_overrides: dict[str, object] | None = None,
) -> tuple[TestClient, int]:
    bootstrap = run_bootstrap(
        repository,
        resolve_plan(
            _settings(**(settings_overrides or {})),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    )
    return TestClient(_app(repository, storage, settings_overrides)), bootstrap.result.device_row_id


def _device_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_DEVICE_TOKEN}"}


def _record(*, with_media: bool = True) -> Any:
    media_bytes = b"fake-jpeg-bytes" if with_media else None
    return build_record(device_id=_DEVICE_ID, business=BusinessResult.NG, media_content=media_bytes)


def test_object_store_failure_returns_503_without_receipt(repository: CentralRepository) -> None:
    client, device_row_id = _client(repository, storage=FailingObjectStorage())
    with client:
        record = _record()
        accepted = client.post(
            _INGEST_URL, content=build_envelope(record), headers=_device_headers()
        )
        assert accepted.status_code == 201  # inspection metadata is durable

        media_id = record.media[0].media_id
        envelope = build_media_envelope(
            record, source_media_id=media_id, bytes_content=b"fake-jpeg-bytes"
        )
        response = client.post(_INGEST_URL, content=envelope, headers=_device_headers())
        assert response.status_code == 503
        assert response.json()["code"] == "OBJECT_STORE_UNAVAILABLE"
        assert response.headers["Retry-After"] == "5"
        # No false success receipt and no binding was persisted for the media.
        assert response.json().get("central_object_id") is None
        assert repository.get_media_binding(device_row_id, str(media_id)) is None


def test_database_failure_returns_503_with_retry_after(
    repository: CentralRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _client(repository)
    with client:
        record = _record(with_media=False)

        def _broken(*args: Any, **kwargs: Any) -> Any:
            raise OperationalError("SELECT 1", {}, Exception("connection lost"))

        monkeypatch.setattr(repository, "ingest_inspection", _broken)
        response = client.post(
            _INGEST_URL, content=build_envelope(record), headers=_device_headers()
        )
        assert response.status_code == 503
        assert response.json()["code"] == "DATABASE_UNAVAILABLE"
        assert response.headers["Retry-After"] == "5"


def test_rate_limit_returns_429_with_retry_after(repository: CentralRepository) -> None:
    client, _ = _client(repository, settings_overrides={"rate_limit_requests_per_minute": 3})
    with client:
        # Health endpoints are never limited (orchestrator probes).
        for _ in range(6):
            health = client.get("/api/v1/health/live")
            assert health.status_code == 200
        # Exceed the window for one client identity.
        for _ in range(3):
            response = client.get("/api/v1/products")
            assert response.status_code in (200, 401)  # admin routes need auth but count
        limited = client.get("/api/v1/products")
        assert limited.status_code == 429
        assert limited.json()["code"] == "RATE_LIMITED"
        assert int(limited.headers["Retry-After"]) >= 1
