"""C6 backup/restore representative tests.

A consistent snapshot is taken with SQLite ``VACUUM INTO`` (the closest
representative of ``pg_dump`` for the automated suite; the PostgreSQL
procedure is documented in the central backup/restore runbook). Restoring
means opening the snapshot as a fresh database and proving accepted
inspections, media bindings, receipts, and audit events are intact and the
receipts remain replayable.
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
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()


def _settings() -> CentralSettings:
    return CentralSettings(  # type: ignore[arg-type]
        database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        admin_session_ttl_minutes=60,
        secure_cookies=False,
    )


def _open_repository(path: str) -> CentralRepository:
    engine = create_engine(f"sqlite+pysqlite:///{path}", poolclass=NullPool)
    metadata.create_all(engine)
    return CentralRepository(engine)


def test_backup_restore_preserves_data_and_replayability(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_file = str(tmp_path / "central.db")
    snapshot_file = str(tmp_path / "central-snapshot.db")
    storage = NoopObjectStorage()

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

    # Controlled backup: a consistent snapshot of the live database.
    with repository._engine.connect() as connection:  # noqa: SLF001 - test drives VACUUM INTO
        connection.execute(text(f"VACUUM INTO '{snapshot_file}'"))
    repository._engine.dispose()  # noqa: SLF001 - close the primary before restore

    # Representative restore: open the snapshot as a fresh database.
    restored = _open_repository(snapshot_file)
    detail = restored.get_inspection_detail(bootstrap.organization_id, str(record.inspection_id))
    assert detail is not None
    assert detail.summary.business_result == "NG"
    assert len(detail.media) == 1

    # The restored receipts are replayable and byte-identical.
    restored_device = restored.get_device(bootstrap.organization_id, bootstrap.device_row_id)
    assert restored_device is not None
    replay = ingest_upload(
        repository=restored,
        storage=storage,
        device=restored_device,
        body=build_envelope(record),
        settings=_settings(),
        received_at=datetime.now(UTC),
    )
    assert replay.replayed
    assert replay.receipt.object_id == accepted.receipt.object_id
    media_replay = ingest_upload(
        repository=restored,
        storage=storage,
        device=restored_device,
        body=media_envelope,
        settings=_settings(),
        received_at=datetime.now(UTC),
    )
    assert media_replay.replayed
    assert media_replay.receipt.central_object_id == media_receipt.receipt.central_object_id

    # The restored database is schema-complete (schema + audit rows).
    with restored._engine.connect() as connection:  # noqa: SLF001 - test reads audit
        schema_row = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).all()
        audit_count = connection.execute(
            select(metadata.tables["audit_logs"].c.id).where(
                metadata.tables["audit_logs"].c.organization_id == bootstrap.organization_id
            )
        ).all()
    table_names = {row[0] for row in schema_row}
    assert {"inspections", "upload_receipts", "inspection_media", "audit_logs"}.issubset(
        table_names
    )
    assert len(audit_count) >= 2
    restored._engine.dispose()  # noqa: SLF001 - cleanup
