"""Central pilot persistence repository (C1b).

Typed row access for the tenant/device/credential domain. Every tenant-owned
query takes an explicit ``organization_id`` and is scoped server-side in SQL;
authentication looks up credentials by token and fails closed on unknown,
disabled, or mismatched rows. Session tokens are split into a public lookup
half and a hashed secret half so resolution is one indexed query.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, Select, and_, select
from sqlalchemy.engine import RowMapping

from central_service.auth.passwords import CredentialHash, hash_credential, verify_credential
from central_service.persistence.schema import (
    admin_sessions,
    administrators,
    audit_logs,
    devices,
    organizations,
    production_lines,
    sites,
)

_SESSION_LOOKUP_BYTES = 16
_SESSION_SECRET_BYTES = 32
_ACTIVE = "ACTIVE"


def _utc(value: datetime) -> datetime:
    """Return ``value`` normalized to an aware UTC datetime.

    SQLite returns naive datetimes for ``DateTime(timezone=True)`` columns;
    PostgreSQL returns aware ones. Naive values are interpreted as UTC so
    callers always compare aware clocks.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_to_datetime(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None


@dataclass(frozen=True)
class SiteRow:
    id: int
    organization_id: int
    name: str
    created_at: datetime


@dataclass(frozen=True)
class LineRow:
    id: int
    site_id: int
    organization_id: int
    name: str
    created_at: datetime


@dataclass(frozen=True)
class DeviceRow:
    id: int
    organization_id: int
    site_id: int
    production_line_id: int
    device_id: str
    name: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class AdministratorRow:
    id: int
    organization_id: int
    username: str
    created_at: datetime


@dataclass(frozen=True)
class PilotBootstrapResult:
    """Outcome of an idempotent pilot bootstrap run."""

    organization_id: int
    site_id: int
    production_line_id: int
    device_id: str
    device_row_id: int
    administrator_id: int
    created: tuple[str, ...]

    @property
    def bootstrapped(self) -> bool:
        return bool(self.created)


class CentralRepository:
    """Typed read/write access to the central pilot schema."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- tenant queries (organization-scoped) ---------------------------------

    def list_sites(self, organization_id: int) -> list[SiteRow]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(sites)
                .where(sites.c.organization_id == organization_id)
                .order_by(sites.c.name)
            ).mappings()
            return [self._site_from_row(row) for row in rows]

    def list_lines(self, organization_id: int, site_id: int | None = None) -> list[LineRow]:
        statement: Select[Any] = select(production_lines).where(
            production_lines.c.organization_id == organization_id
        )
        if site_id is not None:
            statement = statement.where(production_lines.c.site_id == site_id)
        statement = statement.order_by(production_lines.c.name)
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings()
            return [self._line_from_row(row) for row in rows]

    def list_devices(self, organization_id: int) -> list[DeviceRow]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(devices)
                .where(devices.c.organization_id == organization_id)
                .order_by(devices.c.device_id)
            ).mappings()
            return [self._device_from_row(row) for row in rows]

    def get_device(self, organization_id: int, device_row_id: int) -> DeviceRow | None:
        statement = select(devices).where(
            and_(devices.c.id == device_row_id, devices.c.organization_id == organization_id)
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return self._device_from_row(row) if row is not None else None

    # -- credential authentication --------------------------------------------

    def authenticate_device(self, token: str) -> DeviceRow | None:
        """Resolve ``token`` to the single active registered device, or None.

        The token is verified against every stored hash because salts are
        random per row; the pilot fleet is small and scrypt dominates the
        cost. Disabled devices never authenticate.
        """
        with self._engine.connect() as connection:
            rows = connection.execute(select(devices)).mappings().all()
        for row in rows:
            device = self._device_from_row(row)
            if device.status != _ACTIVE:
                continue
            stored = CredentialHash(salt=row["upload_token_salt"], digest=row["upload_token_hash"])
            if verify_credential(token, stored):
                return device
        return None

    def authenticate_administrator(self, token: str) -> AdministratorRow | None:
        with self._engine.connect() as connection:
            rows = connection.execute(select(administrators)).mappings().all()
        for row in rows:
            stored = CredentialHash(salt=row["token_salt"], digest=row["token_hash"])
            if verify_credential(token, stored):
                return self._administrator_from_row(row)
        return None

    # -- administrator browser sessions ---------------------------------------

    def create_admin_session(
        self, administrator_id: int, organization_id: int, ttl: timedelta
    ) -> str:
        """Create a session and return its single-use bearer token.

        The token is split into a public lookup half and a secret half stored
        only as a salted hash, so a leaked sessions table cannot forge one.
        The session row carries the administrator's organization scope so
        every tenant-owned row stays scoped (C1 invariant 6).
        """
        token = secrets.token_urlsafe(_SESSION_LOOKUP_BYTES + _SESSION_SECRET_BYTES)
        lookup = token[:_SESSION_LOOKUP_BYTES]
        secret = token[_SESSION_LOOKUP_BYTES:]
        stored = hash_credential(secret)
        expires_at = datetime.now(UTC) + ttl
        with self._engine.begin() as connection:
            connection.execute(
                admin_sessions.insert().values(
                    administrator_id=administrator_id,
                    organization_id=organization_id,
                    session_lookup=lookup,
                    session_token_hash=stored.digest,
                    session_token_salt=stored.salt,
                    expires_at=expires_at,
                )
            )
        return token

    def resolve_admin_session(self, session_token: str) -> AdministratorRow | None:
        """Return the administrator owning a live session token, or None."""
        if len(session_token) < _SESSION_LOOKUP_BYTES + _SESSION_SECRET_BYTES:
            return None
        lookup = session_token[:_SESSION_LOOKUP_BYTES]
        secret = session_token[_SESSION_LOOKUP_BYTES:]
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(admin_sessions).where(admin_sessions.c.session_lookup == lookup)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        expires_at = _utc(row["expires_at"])
        if expires_at <= datetime.now(UTC):
            return None
        stored = CredentialHash(salt=row["session_token_salt"], digest=row["session_token_hash"])
        if not verify_credential(secret, stored):
            return None
        with self._engine.connect() as connection:
            admin_row = (
                connection.execute(
                    select(administrators).where(administrators.c.id == row["administrator_id"])
                )
                .mappings()
                .first()
            )
        if admin_row is None:
            return None
        administrator = self._administrator_from_row(admin_row)
        # Defensive consistency check: a session row must belong to the same
        # organization as its administrator.
        if administrator.organization_id != int(row["organization_id"]):
            return None
        return administrator

    def purge_expired_sessions(self) -> int:
        """Delete expired sessions and return the number removed."""
        with self._engine.begin() as connection:
            result = connection.execute(
                admin_sessions.delete().where(admin_sessions.c.expires_at <= datetime.now(UTC))
            )
        return int(result.rowcount)

    # -- pilot bootstrap -------------------------------------------------------

    def bootstrap_pilot(
        self,
        *,
        organization_name: str,
        site_name: str,
        line_name: str,
        device_id: str,
        device_name: str,
        device_upload_token: str,
        admin_username: str,
        admin_token: str,
    ) -> PilotBootstrapResult:
        """Create the pilot organization/site/line/device/administrator.

        Idempotent by name/identity: existing rows are reused, and an existing
        device or administrator is never re-created or re-keyed. The pilot
        enrollment and its mandatory bootstrap audit event commit in one
        transaction, so a failed audit rolls the whole enrollment back and no
        active credential can exist without its audit record.
        """
        created: list[str] = []
        with self._engine.begin() as connection:
            organization_row = (
                connection.execute(
                    select(organizations).where(organizations.c.name == organization_name)
                )
                .mappings()
                .first()
            )
            if organization_row is None:
                organization_row = (
                    connection.execute(
                        organizations.insert()
                        .values(name=organization_name)
                        .returning(*organizations.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("organization")
            organization_id = int(organization_row["id"])

            site_row = (
                connection.execute(
                    select(sites).where(
                        and_(sites.c.organization_id == organization_id, sites.c.name == site_name)
                    )
                )
                .mappings()
                .first()
            )
            if site_row is None:
                site_row = (
                    connection.execute(
                        sites.insert()
                        .values(organization_id=organization_id, name=site_name)
                        .returning(*sites.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("site")
            site_id = int(site_row["id"])

            line_row = (
                connection.execute(
                    select(production_lines).where(
                        and_(
                            production_lines.c.site_id == site_id,
                            production_lines.c.name == line_name,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if line_row is None:
                line_row = (
                    connection.execute(
                        production_lines.insert()
                        .values(organization_id=organization_id, site_id=site_id, name=line_name)
                        .returning(*production_lines.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("production_line")
            line_id = int(line_row["id"])

            device_row = (
                connection.execute(
                    select(devices).where(
                        and_(
                            devices.c.organization_id == organization_id,
                            devices.c.device_id == device_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if device_row is None:
                device_hash = hash_credential(device_upload_token)
                device_row = (
                    connection.execute(
                        devices.insert()
                        .values(
                            organization_id=organization_id,
                            site_id=site_id,
                            production_line_id=line_id,
                            device_id=device_id,
                            name=device_name,
                            status=_ACTIVE,
                            upload_token_hash=device_hash.digest,
                            upload_token_salt=device_hash.salt,
                        )
                        .returning(*devices.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("device")
            device_row_id = int(device_row["id"])

            admin_row = (
                connection.execute(
                    select(administrators).where(
                        and_(
                            administrators.c.organization_id == organization_id,
                            administrators.c.username == admin_username,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if admin_row is None:
                admin_hash = hash_credential(admin_token)
                admin_row = (
                    connection.execute(
                        administrators.insert()
                        .values(
                            organization_id=organization_id,
                            username=admin_username,
                            token_hash=admin_hash.digest,
                            token_salt=admin_hash.salt,
                        )
                        .returning(*administrators.c)
                    )
                    .mappings()
                    .one()
                )
                created.append("administrator")
            administrator_id = int(admin_row["id"])

            connection.execute(
                audit_logs.insert().values(
                    organization_id=organization_id,
                    actor_type="SYSTEM",
                    actor_id=None,
                    action="PILOT_BOOTSTRAP",
                    target_type="pilot",
                    target_id=str(organization_id),
                    detail=f"created={','.join(created) or 'none'}",
                )
            )

        return PilotBootstrapResult(
            organization_id=organization_id,
            site_id=site_id,
            production_line_id=line_id,
            device_id=device_id,
            device_row_id=device_row_id,
            administrator_id=administrator_id,
            created=tuple(created),
        )

    # -- audit ----------------------------------------------------------------

    def write_audit(
        self,
        *,
        organization_id: int | None,
        actor_type: str,
        actor_id: int | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Append one immutable audit event (contract 08)."""
        with self._engine.begin() as connection:
            connection.execute(
                audit_logs.insert().values(
                    organization_id=organization_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    detail=detail,
                )
            )

    # -- row mappers ----------------------------------------------------------

    def _site_from_row(self, row: RowMapping) -> SiteRow:
        return SiteRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            name=str(row["name"]),
            created_at=self._parse_dt(row["created_at"]),
        )

    def _line_from_row(self, row: RowMapping) -> LineRow:
        return LineRow(
            id=int(row["id"]),
            site_id=int(row["site_id"]),
            organization_id=int(row["organization_id"]),
            name=str(row["name"]),
            created_at=self._parse_dt(row["created_at"]),
        )

    def _device_from_row(self, row: RowMapping) -> DeviceRow:
        return DeviceRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            site_id=int(row["site_id"]),
            production_line_id=int(row["production_line_id"]),
            device_id=str(row["device_id"]),
            name=str(row["name"]),
            status=str(row["status"]),
            created_at=self._parse_dt(row["created_at"]),
        )

    def _administrator_from_row(self, row: RowMapping) -> AdministratorRow:
        return AdministratorRow(
            id=int(row["id"]),
            organization_id=int(row["organization_id"]),
            username=str(row["username"]),
            created_at=self._parse_dt(row["created_at"]),
        )

    @staticmethod
    def _parse_dt(value: object) -> datetime:
        """Normalize a column value (str from SQLite, datetime from PostgreSQL)."""
        if isinstance(value, datetime):
            return _utc(value)
        return _utc(datetime.fromisoformat(str(value)))
