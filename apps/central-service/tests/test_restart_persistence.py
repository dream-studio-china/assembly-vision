"""C6 restart-persistence fault tests.

Proves a controlled restart (engine disposed and reopened against the same
database file) preserves accepted inspections, media bindings, receipts, and
audit events, and that receipts remain replayable after restart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from assemblyvision_domain.models import BusinessResult
from central_service.api.settings import CentralSettings
from central_service.ingest import ingest_upload
from central_service.persistence.bootstrap import resolve_plan, run_bootstrap
from central_service.persistence.repository import CentralRepository
from central_service.persistence.schema import metadata
from ingest_fixtures import (
    NoopObjectStorage,
    build_envelope,
    build_media_envelope,
    build_record,
)
from sqlalchemy import create_engine, select
from sqlalchemy.pool import NullPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()


def _settings() -> CentralSettings:
    return CentralSettings(
        database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        admin_session_ttl_minutes=60,
        secure_cookies=False,
    )


def _open_repository(path: str) -> CentralRepository:
    engine = create_engine(f"sqlite+pysqlite:///{path}", poolclass=NullPool)
    metadata.create_all(engine)
    return CentralRepository(engine)


def test_restart_preserves_inspections_receipts_and_bindings(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_file = str(tmp_path / "central.db")
    storage = NoopObjectStorage()

    # First process lifetime: bootstrap and accept an inspection + media.
    repository = _open_repository(db_file)
    bootstrap = run_bootstrap(
        repository,
        resolve_plan(
            _settings(),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    ).result
    device = repository.get_device(bootstrap.organization_id, bootstrap.device_row_id)
    assert device is not None

    record = build_record(
        device_id=_DEVICE_ID, business=BusinessResult.NG, media_content=b"fake-jpeg-bytes"
    )
    accepted = ingest_upload(
        repository=repository,
        storage=storage,
        device=device,
        body=build_envelope(record),
        settings=_settings(),
        received_at=datetime.now(UTC),
    )
    assert not accepted.replayed
    media_envelope = build_media_envelope(
        record,
        source_media_id=record.media[0].media_id,
        bytes_content=b"fake-jpeg-bytes",
    )
    media_receipt = ingest_upload(
        repository=repository,
        storage=storage,
        device=device,
        body=media_envelope,
        settings=_settings(),
        received_at=datetime.now(UTC),
    )
    assert not media_receipt.replayed
    repository._engine.dispose()  # noqa: SLF001 - simulates a controlled restart

    # Second process lifetime: reopen the same database file.
    restarted = _open_repository(db_file)
    detail = restarted.get_inspection_detail(bootstrap.organization_id, str(record.inspection_id))
    assert detail is not None
    assert detail.summary.business_result == "NG"
    assert len(detail.media) == 1
    assert detail.media[0].source_media_id == str(record.media[0].media_id)
    assert detail.media[0].lifecycle == "AVAILABLE"

    # The receipt for the inspection is still replayable (idempotent replay).
    restarted_device = restarted.get_device(bootstrap.organization_id, bootstrap.device_row_id)
    assert restarted_device is not None
    replay = ingest_upload(
        repository=restarted,
        storage=storage,
        device=restarted_device,
        body=build_envelope(record),
        settings=_settings(),
        received_at=datetime.now(UTC),
    )
    assert replay.replayed
    assert replay.receipt.object_id == str(record.inspection_id)

    # Media receipt replay is duplicate-free and returns the same object id.
    media_replay = ingest_upload(
        repository=restarted,
        storage=storage,
        device=restarted_device,
        body=media_envelope,
        settings=_settings(),
        received_at=datetime.now(UTC),
    )
    assert media_replay.replayed
    assert media_replay.receipt.central_object_id == media_receipt.receipt.central_object_id

    # Audit events written before the restart survive.
    with restarted._engine.connect() as connection:  # noqa: SLF001 - test reads audit
        audit_count = connection.execute(
            select(metadata.tables["audit_logs"].c.id).where(
                metadata.tables["audit_logs"].c.organization_id == bootstrap.organization_id
            )
        ).all()
    assert len(audit_count) >= 2  # bootstrap + accepted inspection (+ media)
    restarted._engine.dispose()  # noqa: SLF001 - cleanup
