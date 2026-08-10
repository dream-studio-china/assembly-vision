"""Readiness probes for /health/ready (C1a).

Readiness fails when any required dependency is unavailable or misconfigured:
PostgreSQL reachable with the schema at head, MinIO bucket access, and valid
pilot credential configuration. Details stay bounded and never include
credentials, object keys, or internal paths.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from central_service.api.settings import CentralSettings
from central_service.persistence.migrate import current_head
from central_service.storage.object_store import ObjectStorage

_CREDENTIAL_MIN_LENGTH = 16


@dataclass(frozen=True)
class ReadinessCheck:
    """Result of one dependency probe."""

    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class ReadinessResult:
    """Aggregate readiness outcome."""

    checks: tuple[ReadinessCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


def probe_database(engine: Engine) -> ReadinessCheck:
    """Check PostgreSQL reachability and schema-at-head state."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
    except SQLAlchemyError:
        return ReadinessCheck(name="database", ok=False, detail="unreachable")
    applied = str(row[0]) if row is not None else None
    if applied is None:
        return ReadinessCheck(name="database", ok=False, detail="schema not migrated")
    if applied != current_head():
        return ReadinessCheck(name="database", ok=False, detail="schema behind head")
    return ReadinessCheck(name="database", ok=True, detail="ok")


def probe_object_store(storage: ObjectStorage) -> ReadinessCheck:
    """Check the configured object-store bucket is reachable."""
    try:
        ready = storage.bucket_ready()
    except Exception:  # noqa: BLE001 - any storage client failure means not ready
        return ReadinessCheck(name="object_store", ok=False, detail="unreachable")
    if not ready:
        return ReadinessCheck(name="object_store", ok=False, detail="bucket missing")
    return ReadinessCheck(name="object_store", ok=True, detail="ok")


def probe_credentials(settings: CentralSettings) -> ReadinessCheck:
    """Check the pilot credential configuration is valid (C1a)."""
    if settings.admin_token is None or len(settings.admin_token) < _CREDENTIAL_MIN_LENGTH:
        return ReadinessCheck(
            name="credentials", ok=False, detail="pilot admin token not configured"
        )
    return ReadinessCheck(name="credentials", ok=True, detail="ok")


def compute_readiness(
    engine: Engine, storage: ObjectStorage, settings: CentralSettings
) -> ReadinessResult:
    """Run every probe against the live dependencies."""
    return ReadinessResult(
        checks=(probe_database(engine), probe_object_store(storage), probe_credentials(settings))
    )
