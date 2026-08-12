"""C2a edge-compatibility test (task C1 exit criteria).

Runs the real edge ``HttpUploadSink`` against the central FastAPI
application: the exact envelope the current edge scheduler builds is posted
through the actual edge receipt validator (``_parse_receipt``), so a success
here proves the central receipts satisfy the edge's verified-receipt contract.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from assemblyvision_domain.models import InspectionRecord, UploadTask
from assemblyvision_edge.upload.scheduler import HttpUploadSink
from central_service.api.app import create_app
from central_service.api.readiness import ReadinessCheck, ReadinessResult
from central_service.api.settings import CentralSettings
from central_service.persistence.bootstrap import resolve_plan, run_bootstrap
from central_service.persistence.repository import CentralRepository
from central_service.persistence.schema import metadata
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ingest_fixtures import NoopObjectStorage, build_record, canonical_payload, content_hash
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


def _task(
    record: InspectionRecord, *, kind: str = "INSPECTION", checksum: str | None = None
) -> UploadTask:
    now = datetime.now(UTC)
    if kind == "INSPECTION":
        return UploadTask(
            upload_task_id=uuid4(),
            device_id=record.device_id,
            inspection_id=record.inspection_id,
            kind="INSPECTION",
            object_id=record.inspection_id,
            payload_hash=content_hash(record),
            status="PENDING",
            idempotency_key=f"inspection:{record.device_id}:{record.inspection_id}",
            checksum_sha256=content_hash(record),
            attempt_count=0,
            next_attempt_at=None,
            last_error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
    return UploadTask(
        upload_task_id=uuid4(),
        device_id=record.device_id,
        inspection_id=record.inspection_id,
        kind="MEDIA",
        object_id=uuid4(),
        payload_hash=checksum or "0" * 64,
        status="PENDING",
        idempotency_key=f"media:{record.device_id}:{uuid4()}",
        checksum_sha256=checksum or "0" * 64,
        attempt_count=0,
        next_attempt_at=None,
        last_error_code=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


def _sink(client: TestClient) -> HttpUploadSink:
    return HttpUploadSink(base_url="http://testserver/api/v1", token=_DEVICE_TOKEN, client=client)


def test_real_edge_sink_accepts_verified_receipt(client: TestClient) -> None:
    record = build_record(device_id=_DEVICE_ID)
    sink = _sink(client)
    result = sink.upload(_task(record), canonical_payload(record))
    assert result.status == "SUCCEEDED"
    assert result.receipt is not None
    assert result.receipt.idempotency_key == f"inspection:{record.device_id}:{record.inspection_id}"
    assert result.receipt.checksum_sha256 == content_hash(record)
    assert result.receipt.size_bytes == len(canonical_payload(record))
    assert result.receipt.central_object_id is None


def test_real_edge_sink_replay_is_verified_success(client: TestClient) -> None:
    record = build_record(device_id=_DEVICE_ID)
    sink = _sink(client)
    payload = canonical_payload(record)
    first = sink.upload(_task(record), payload)
    second = sink.upload(_task(record), payload)
    assert first.status == "SUCCEEDED"
    assert second.status == "SUCCEEDED"
    assert first.receipt is not None and second.receipt is not None
    assert second.receipt.idempotency_key == first.receipt.idempotency_key
    assert second.receipt.checksum_sha256 == first.receipt.checksum_sha256
    assert second.receipt.size_bytes == first.receipt.size_bytes


def test_real_edge_sink_payload_conflict_is_permanent(client: TestClient) -> None:
    record = build_record(device_id=_DEVICE_ID)
    sink = _sink(client)
    first = sink.upload(_task(record), canonical_payload(record))
    assert first.status == "SUCCEEDED"
    changed = record.model_copy(update={"processing_ms": record.processing_ms + 1})
    conflict = sink.upload(_task(changed), canonical_payload(changed))
    assert conflict.status == "PERMANENT"
    assert conflict.error_code == "HTTP_409"


def test_real_edge_sink_media_is_retryable_503(client: TestClient) -> None:
    record = build_record(device_id=_DEVICE_ID)
    sink = _sink(client)
    media_bytes = b"fake-media-bytes"
    result = sink.upload(
        _task(record, kind="MEDIA", checksum=hashlib.sha256(media_bytes).hexdigest()), media_bytes
    )
    assert result.status == "RETRYABLE"
    assert result.error_code == "HTTP_503"
