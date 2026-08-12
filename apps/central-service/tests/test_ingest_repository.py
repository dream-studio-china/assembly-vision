"""CentralRepository ingestion tests (C2a).

Exercise the single-transaction persist path, identical replay returning the
original receipt, and the three payload-conflict identities (idempotency key,
inspection id, device sequence) on SQLite with foreign keys enforced.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from assemblyvision_domain.models import BusinessResult
from central_service.persistence.repository import (
    CentralRepository,
    PayloadConflictError,
    PilotBootstrapResult,
    _integrity_constraint,
)
from central_service.persistence.schema import (
    audit_logs,
    inspection_components,
    inspection_media,
    inspections,
    metadata,
    upload_receipts,
)
from ingest_fixtures import build_record, canonical_payload, content_hash
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
# The registered edge identity; the payload device_id must match exactly. The
# UUID object is kept so records carry a typed UUID like the real edge.
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
def sqlite_engine() -> Iterator[Engine]:
    engine = _sqlite_engine()
    yield engine
    engine.dispose()


@pytest.fixture
def repository(sqlite_engine: Engine) -> CentralRepository:
    return CentralRepository(sqlite_engine)


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


def _ingest(
    repository: CentralRepository,
    device: PilotBootstrapResult,
    record: Any,
) -> tuple[Any, bool]:
    device_row = repository.get_device(device.organization_id, device.device_row_id)
    assert device_row is not None
    return repository.ingest_inspection(
        device=device_row,
        idempotency_key=f"inspection:{record.device_id}:{record.inspection_id}",
        request_hash=content_hash(record),
        object_id=str(record.inspection_id),
        inspection_id=str(record.inspection_id),
        record=record,
        payload_json=canonical_payload(record).decode("utf-8"),
        received_at=datetime.now(UTC),
    )


def _record(**overrides: Any) -> Any:
    values: dict[str, Any] = {"device_id": _DEVICE_ID}
    values.update(overrides)
    return build_record(**values)


def test_ingest_persists_inspection_receipt_components_and_audit(
    sqlite_engine: Engine, repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    record = _record()
    receipt, replayed = _ingest(repository, device, record)
    assert replayed is False
    assert receipt.kind == "INSPECTION"
    assert receipt.request_hash == content_hash(record)
    assert receipt.size_bytes == len(canonical_payload(record))
    assert receipt.idempotency_key == f"inspection:{record.device_id}:{record.inspection_id}"

    with sqlite_engine.connect() as connection:
        inspection_rows = connection.execute(select(inspections)).mappings().all()
        component_rows = connection.execute(select(inspection_components)).mappings().all()
        receipt_rows = connection.execute(select(upload_receipts)).mappings().all()
        audit_actions = [
            str(row["action"]) for row in connection.execute(select(audit_logs.c.action)).mappings()
        ]
    assert len(inspection_rows) == 1
    row = inspection_rows[0]
    assert str(row["inspection_id"]) == str(record.inspection_id)
    assert int(row["device_sequence"]) == record.device_sequence
    assert str(row["business_result"]) == "NG"
    assert str(row["internal_decision"]) == "NG"
    assert str(row["payload_json"]) == canonical_payload(record).decode("utf-8")
    assert str(row["request_hash"]) == content_hash(record)
    assert len(component_rows) == 1
    assert str(component_rows[0]["component_code"]) == "component_a"
    assert str(component_rows[0]["state"]) == "MISSING"
    assert len(receipt_rows) == 1
    assert "INSPECTION_ACCEPTED" in audit_actions
    assert "UPLOAD_PAYLOAD_CONFLICT" not in audit_actions


def test_identical_replay_returns_original_receipt_without_duplicates(
    sqlite_engine: Engine, repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    record = _record()
    first, replayed_first = _ingest(repository, device, record)
    second, replayed_second = _ingest(repository, device, record)
    assert replayed_first is False
    assert replayed_second is True
    assert second.idempotency_key == first.idempotency_key
    assert second.request_hash == first.request_hash
    assert second.created_at == first.created_at

    with sqlite_engine.connect() as connection:
        inspection_count = connection.execute(select(func.count(inspections.c.id))).scalar_one()
        receipt_count = connection.execute(select(func.count(upload_receipts.c.id))).scalar_one()
        acceptance_audits = connection.execute(
            select(audit_logs.c.action).where(audit_logs.c.action == "INSPECTION_ACCEPTED")
        ).all()
    assert int(inspection_count) == 1
    assert int(receipt_count) == 1
    assert len(acceptance_audits) == 1


def test_idempotency_key_reuse_with_different_hash_conflicts(
    sqlite_engine: Engine, repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    first = _record()
    _ingest(repository, device, first)
    changed = first.model_copy(update={"processing_ms": first.processing_ms + 1})
    with pytest.raises(PayloadConflictError):
        _ingest(repository, device, changed)

    with sqlite_engine.connect() as connection:
        inspection_count = connection.execute(select(func.count(inspections.c.id))).scalar_one()
        conflict_audits = connection.execute(
            select(audit_logs.c.action).where(audit_logs.c.action == "UPLOAD_PAYLOAD_CONFLICT")
        ).all()
        stored_hash = connection.execute(select(inspections.c.request_hash)).scalar_one()
    assert int(inspection_count) == 1  # original preserved
    assert len(conflict_audits) == 1
    assert str(stored_hash) == content_hash(first)


def test_inspection_id_reuse_with_different_key_conflicts(
    sqlite_engine: Engine, repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    first = _record()
    _ingest(repository, device, first)
    duplicate = build_record(
        device_id=_DEVICE_ID,
        inspection_id=first.inspection_id,
        device_sequence=first.device_sequence + 1,
    )
    with pytest.raises(PayloadConflictError):
        _ingest(repository, device, duplicate)


def test_device_sequence_reuse_with_different_hash_conflicts(
    sqlite_engine: Engine, repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    first = _record(device_sequence=7)
    _ingest(repository, device, first)
    different = _record(device_sequence=7)
    assert str(different.inspection_id) != str(first.inspection_id)
    with pytest.raises(PayloadConflictError):
        _ingest(repository, device, different)


def test_get_receipt_returns_persisted_row(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    record = _record()
    ingested, _ = _ingest(repository, device, record)
    device_row = repository.get_device(device.organization_id, device.device_row_id)
    assert device_row is not None
    fetched = repository.get_receipt(
        device_row, f"inspection:{record.device_id}:{record.inspection_id}"
    )
    assert fetched is not None
    assert fetched.idempotency_key == ingested.idempotency_key
    assert fetched.size_bytes == len(canonical_payload(record))
    assert repository.get_receipt(device_row, "inspection:unknown:key") is None


def test_ok_inspection_is_persisted_with_present_evidence(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    record = _record(business=BusinessResult.OK)
    receipt, replayed = _ingest(repository, device, record)
    assert replayed is False
    assert receipt.request_hash == content_hash(record)


class _FakeDiag:
    constraint_name = "uq_upload_receipts_device_key"


class _FakeOrig(Exception):
    diag = _FakeDiag()


def test_integrity_constraint_name_detection() -> None:
    assert (
        _integrity_constraint(IntegrityError("stmt", {}, _FakeOrig()))
        == "uq_upload_receipts_device_key"
    )
    # SQLite-style errors expose no diag, so the name stays None and the
    # non-conflict path re-raises the integrity error.
    assert (
        _integrity_constraint(IntegrityError("stmt", {}, Exception("UNIQUE constraint failed")))
        is None
    )


def test_concurrent_unique_race_maps_to_payload_conflict(
    sqlite_engine: Engine,
    repository: CentralRepository,
    device: PilotBootstrapResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost insert race on an ingestion uniqueness constraint is a 409.

    The database is authoritative for effectively-once persistence: an
    IntegrityError on the receipt/inspection identity constraints (the
    PostgreSQL diag path, simulated here) must surface as a payload conflict
    with an audit event, never as an internal error.
    """
    record = _record()

    def _receipt_insert_fails(*args: object, **kwargs: object) -> object:
        raise IntegrityError("INSERT", {}, _FakeOrig())

    # The receipt insert is the last write in the transaction; failing it
    # simulates a lost unique-constraint race after the inspection insert.
    monkeypatch.setattr(upload_receipts, "insert", _receipt_insert_fails)
    with pytest.raises(PayloadConflictError):
        _ingest(repository, device, record)

    with sqlite_engine.connect() as connection:
        inspection_count = connection.execute(select(func.count(inspections.c.id))).scalar_one()
        conflict_audits = connection.execute(
            select(audit_logs.c.action).where(audit_logs.c.action == "UPLOAD_PAYLOAD_CONFLICT")
        ).all()
    # The failed transaction rolled back and the conflict was audited.
    assert int(inspection_count) == 0
    assert len(conflict_audits) == 1


# -- C2b media binding -------------------------------------------------------


def _ingest_media(
    repository: CentralRepository,
    device: PilotBootstrapResult,
    record: Any,
    *,
    idempotency_key: str | None = None,
    request_hash: str | None = None,
    central_object_id: str | None = None,
    object_key: str | None = None,
) -> tuple[Any, bool]:
    device_row = repository.get_device(device.organization_id, device.device_row_id)
    assert device_row is not None
    media = record.media[0]
    lookup = repository.get_inspection_media_manifest(device_row.id, str(record.inspection_id))
    assert lookup is not None
    inspection_row_id, capture_at, _manifest = lookup
    return repository.persist_media(
        device=device_row,
        inspection_row_id=inspection_row_id,
        idempotency_key=idempotency_key or f"media:{record.device_id}:{media.media_id}",
        request_hash=request_hash or media.checksum_sha256,
        object_id=str(media.media_id),
        inspection_id=str(record.inspection_id),
        central_object_id=central_object_id or str(uuid4()),
        object_key=object_key or f"org/1/device/{_DEVICE_ID}/2026/08/{media.media_id}",
        media_kind=media.kind,
        mime_type=media.mime_type,
        size_bytes=media.size_bytes,
        checksum_sha256=media.checksum_sha256,
        capture_at=capture_at,
        received_at=datetime.now(UTC),
    )


def test_get_inspection_media_manifest_parses_accepted_payload(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    media_bytes = b"fake-jpeg-bytes"
    record = _record(media_content=media_bytes)
    _ingest(repository, device, record)
    device_row = repository.get_device(device.organization_id, device.device_row_id)
    assert device_row is not None
    lookup = repository.get_inspection_media_manifest(device_row.id, str(record.inspection_id))
    assert lookup is not None
    inspection_row_id, capture_at, manifest = lookup
    assert inspection_row_id > 0
    assert capture_at.tzinfo is not None
    media = record.media[0]
    entry = manifest[str(media.media_id)]
    assert entry.media_kind == "KEY_FRAME"
    assert entry.mime_type == "image/jpeg"
    assert entry.size_bytes == len(media_bytes)
    assert entry.checksum_sha256 == hashlib.sha256(media_bytes).hexdigest()
    # Unknown parent inspection returns None.
    assert repository.get_inspection_media_manifest(device_row.id, str(uuid4())) is None


def test_persist_media_creates_binding_receipt_and_audit(
    sqlite_engine: Engine, repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    record = _record(media_content=b"fake-jpeg-bytes")
    _ingest(repository, device, record)
    receipt, replayed = _ingest_media(repository, device, record)
    assert replayed is False
    assert receipt.kind == "MEDIA"
    assert receipt.central_object_id is not None

    with sqlite_engine.connect() as connection:
        media_rows = connection.execute(select(inspection_media)).mappings().all()
        receipt_rows = connection.execute(select(upload_receipts)).mappings().all()
        audit_actions = [
            str(row["action"]) for row in connection.execute(select(audit_logs.c.action)).mappings()
        ]
    assert len(media_rows) == 1
    media_row = media_rows[0]
    assert str(media_row["source_media_id"]) == str(record.media[0].media_id)
    assert str(media_row["lifecycle"]) == "AVAILABLE"
    assert str(media_row["central_object_id"]) == receipt.central_object_id
    assert len(receipt_rows) == 2  # inspection + media
    assert "MEDIA_ACCEPTED" in audit_actions


def test_media_identical_replay_returns_original_receipt_without_duplicates(
    sqlite_engine: Engine, repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    record = _record(media_content=b"fake-jpeg-bytes")
    _ingest(repository, device, record)
    first, replayed_first = _ingest_media(repository, device, record)
    second, replayed_second = _ingest_media(repository, device, record)
    assert replayed_first is False
    assert replayed_second is True
    assert second.central_object_id == first.central_object_id

    with sqlite_engine.connect() as connection:
        media_count = connection.execute(select(func.count(inspection_media.c.id))).scalar_one()
        media_receipts = connection.execute(
            select(func.count(upload_receipts.c.id)).where(upload_receipts.c.kind == "MEDIA")
        ).scalar_one()
    assert int(media_count) == 1
    assert int(media_receipts) == 1


def test_media_source_id_reuse_with_different_hash_conflicts(
    sqlite_engine: Engine, repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    record = _record(media_content=b"fake-jpeg-bytes")
    _ingest(repository, device, record)
    _ingest_media(repository, device, record)
    with pytest.raises(PayloadConflictError):
        _ingest_media(
            repository,
            device,
            record,
            request_hash="1" * 64,
            central_object_id=str(uuid4()),
        )
    with sqlite_engine.connect() as connection:
        media_count = connection.execute(select(func.count(inspection_media.c.id))).scalar_one()
    assert int(media_count) == 1  # original binding preserved


def test_media_replay_conflict_writes_audit(
    sqlite_engine: Engine, repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    record = _record(media_content=b"fake-jpeg-bytes")
    _ingest(repository, device, record)
    _ingest_media(repository, device, record)
    # A reused key with different content is recorded as a conflict by the
    # service layer through record_payload_conflict; the repository-level
    # replay check is exercised here.
    with pytest.raises(PayloadConflictError):
        _ingest_media(
            repository,
            device,
            record,
            idempotency_key=f"media:{record.device_id}:{record.media[0].media_id}",
            request_hash="2" * 64,
            central_object_id=str(uuid4()),
        )
    with sqlite_engine.connect() as connection:
        conflict_audits = connection.execute(
            select(audit_logs.c.action).where(audit_logs.c.action == "UPLOAD_PAYLOAD_CONFLICT")
        ).all()
    assert len(conflict_audits) == 1
