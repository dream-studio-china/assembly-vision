"""CentralRepository unit tests (C1b).

Every tenant-owned query is exercised with explicit organization scoping, and
credential/session resolution is tested for the closed-failure cases required
by the C1b exit criteria: unknown/disabled tokens, credential-kind separation,
expired sessions, and idempotent bootstrap. SQLite enforces foreign keys in
these tests so the tenant-hierarchy constraints (composite organization-
bound foreign keys) and bootstrap audit atomicity are exercised for real.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from central_service.persistence.repository import CentralRepository, PilotBootstrapResult
from central_service.persistence.schema import (
    admin_sessions,
    audit_logs,
    devices,
    metadata,
    production_lines,
)
from sqlalchemy import Engine, create_engine, event, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105


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


def _bootstrap(
    repository: CentralRepository,
    *,
    organization_name: str = "Org A",
    site_name: str = "Site A",
    device_id: str = "edge-1",
) -> PilotBootstrapResult:
    return repository.bootstrap_pilot(
        organization_name=organization_name,
        site_name=site_name,
        line_name="Line A",
        device_id=device_id,
        device_name="Edge 1",
        device_upload_token=_DEVICE_TOKEN,
        admin_username="admin",
        admin_token=_ADMIN_TOKEN,
    )


def test_bootstrap_creates_all_rows(repository: CentralRepository) -> None:
    result = _bootstrap(repository)
    assert result.organization_id > 0
    assert result.site_id > 0
    assert result.production_line_id > 0
    assert result.device_row_id > 0
    assert result.administrator_id > 0
    assert set(result.created) == {
        "organization",
        "site",
        "production_line",
        "device",
        "administrator",
    }
    assert repository.list_sites(result.organization_id)
    assert repository.list_lines(result.organization_id)
    devices_rows = repository.list_devices(result.organization_id)
    assert len(devices_rows) == 1
    assert devices_rows[0].device_id == "edge-1"


def test_bootstrap_is_idempotent_and_never_rekeys(repository: CentralRepository) -> None:
    first = _bootstrap(repository)
    second = _bootstrap(repository)
    assert second.created == ()
    assert second.organization_id == first.organization_id
    assert second.device_row_id == first.device_row_id
    assert second.administrator_id == first.administrator_id
    # Reusing the same credentials in a second run must not rotate the hashes.
    assert repository.authenticate_device(_DEVICE_TOKEN) is not None
    assert repository.authenticate_administrator(_ADMIN_TOKEN) is not None


def test_device_authentication_ok_and_fails_closed(repository: CentralRepository) -> None:
    _bootstrap(repository)
    device = repository.authenticate_device(_DEVICE_TOKEN)
    assert device is not None
    assert device.device_id == "edge-1"
    assert repository.authenticate_device("wrong-token-0123456789") is None
    assert repository.authenticate_device("") is None


def test_disabled_device_never_authenticates(
    sqlite_engine: Engine, repository: CentralRepository
) -> None:
    result = _bootstrap(repository)
    with sqlite_engine.begin() as connection:
        connection.execute(
            update(devices).where(devices.c.id == result.device_row_id).values(status="DISABLED")
        )
    assert repository.authenticate_device(_DEVICE_TOKEN) is None


def test_administrator_authentication_ok_and_fails_closed(
    repository: CentralRepository,
) -> None:
    _bootstrap(repository)
    administrator = repository.authenticate_administrator(_ADMIN_TOKEN)
    assert administrator is not None
    assert administrator.username == "admin"
    assert repository.authenticate_administrator("wrong-token-0123456789") is None


def test_credential_kinds_cannot_cross_authorize(repository: CentralRepository) -> None:
    _bootstrap(repository)
    # The device upload token must never resolve as an administrator credential
    # and the administrator token must never resolve as a device credential.
    assert repository.authenticate_administrator(_DEVICE_TOKEN) is None
    assert repository.authenticate_device(_ADMIN_TOKEN) is None


def test_admin_session_resolution_and_expiry(repository: CentralRepository) -> None:
    result = _bootstrap(repository)
    token = repository.create_admin_session(
        result.administrator_id, result.organization_id, timedelta(minutes=5)
    )
    resolved = repository.resolve_admin_session(token)
    assert resolved is not None
    assert resolved.id == result.administrator_id
    assert repository.resolve_admin_session("not-a-valid-session-token") is None
    assert repository.resolve_admin_session(token[:-4] + "xxxx") is None


def test_admin_session_carries_organization_scope(
    sqlite_engine: Engine, repository: CentralRepository
) -> None:
    result = _bootstrap(repository)
    repository.create_admin_session(
        result.administrator_id, result.organization_id, timedelta(minutes=5)
    )
    with sqlite_engine.connect() as connection:
        row = connection.execute(select(admin_sessions)).mappings().one()
    assert int(row["organization_id"]) == result.organization_id


def test_admin_session_expired_fails_closed(repository: CentralRepository) -> None:
    result = _bootstrap(repository)
    expired_token = repository.create_admin_session(
        result.administrator_id, result.organization_id, timedelta(seconds=-10)
    )
    assert repository.resolve_admin_session(expired_token) is None
    assert repository.purge_expired_sessions() >= 1


def test_tenant_queries_are_organization_scoped(repository: CentralRepository) -> None:
    first = _bootstrap(repository, organization_name="Org A", device_id="edge-a")
    second = _bootstrap(repository, organization_name="Org B", device_id="edge-b")
    assert first.organization_id != second.organization_id
    org_a_devices = repository.list_devices(first.organization_id)
    org_b_devices = repository.list_devices(second.organization_id)
    assert [d.device_id for d in org_a_devices] == ["edge-a"]
    assert [d.device_id for d in org_b_devices] == ["edge-b"]
    # Cross-organization lookups must return nothing.
    assert repository.get_device(first.organization_id, second.device_row_id) is None
    assert repository.get_device(second.organization_id, first.device_row_id) is None


def test_get_device_unknown_returns_none(repository: CentralRepository) -> None:
    result = _bootstrap(repository)
    assert repository.get_device(result.organization_id, 99999) is None


def test_lines_can_be_filtered_by_site(repository: CentralRepository) -> None:
    result = _bootstrap(repository)
    all_lines = repository.list_lines(result.organization_id)
    site_lines = repository.list_lines(result.organization_id, site_id=result.site_id)
    assert len(all_lines) == 1
    assert len(site_lines) == 1
    assert repository.list_lines(result.organization_id, site_id=99999) == []


def test_cross_tenant_hierarchy_inserts_are_rejected(
    sqlite_engine: Engine, repository: CentralRepository
) -> None:
    """Production lines and devices cannot reference another tenant's nodes.

    The composite foreign keys bind organization_id to the organization of the
    referenced site/line, so a direct insert of a cross-organization hierarchy
    must fail at the database (C1 tenancy isolation).
    """
    org_a = _bootstrap(repository, organization_name="Org A", device_id="edge-a")
    org_b = _bootstrap(repository, organization_name="Org B", device_id="edge-b")

    with pytest.raises(IntegrityError), sqlite_engine.begin() as connection:
        connection.execute(
            production_lines.insert().values(
                organization_id=org_b.organization_id,
                site_id=org_a.site_id,
                name="Cross-tenant line",
            )
        )

    with pytest.raises(IntegrityError), sqlite_engine.begin() as connection:
        connection.execute(
            devices.insert().values(
                organization_id=org_b.organization_id,
                site_id=org_a.site_id,
                production_line_id=org_b.production_line_id,
                device_id="cross-tenant-device",
                name="Cross-tenant device",
                status="ACTIVE",
                upload_token_hash="x" * 64,
                upload_token_salt="y" * 32,
            )
        )


def test_bootstrap_audit_commits_atomically(
    sqlite_engine: Engine, repository: CentralRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed audit insert rolls the whole pilot enrollment back."""

    def _audit_insert_fails(*args: object, **kwargs: object) -> object:
        raise RuntimeError("audit insert failed")

    monkeypatch.setattr(audit_logs, "insert", _audit_insert_fails)
    with pytest.raises(RuntimeError):
        _bootstrap(repository)

    # No credential may exist without its enrollment audit record.
    assert repository.authenticate_device(_DEVICE_TOKEN) is None
    assert repository.authenticate_administrator(_ADMIN_TOKEN) is None
    with sqlite_engine.connect() as connection:
        org_count = connection.execute(text("SELECT COUNT(*) FROM organizations")).scalar_one()
        audit_count = connection.execute(text("SELECT COUNT(*) FROM audit_logs")).scalar_one()
    assert int(org_count) == 0
    assert int(audit_count) == 0


def test_write_audit_appends(sqlite_engine: Engine, repository: CentralRepository) -> None:
    result = _bootstrap(repository)
    repository.write_audit(
        organization_id=result.organization_id,
        actor_type="SYSTEM",
        actor_id=None,
        action="PILOT_BOOTSTRAP",
        target_type="pilot",
        target_id=str(result.organization_id),
    )
    with sqlite_engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM audit_logs")).scalar_one()
    # One audit event from the atomic bootstrap plus the explicit one.
    assert int(count) == 2
