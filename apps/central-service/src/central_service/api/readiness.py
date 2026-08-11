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

from central_service.persistence.migrate import current_head
from central_service.storage.object_store import ObjectStorage


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


def probe_credentials(engine: Engine) -> ReadinessCheck:
    """Check the pilot credential store is bootstrapped (C1b).

    The durable store must contain at least one administrator and one active
    registered device; the API authenticates against hashes in PostgreSQL, so
    an un-bootstrapped pilot is not ready. Fails closed on DB errors.
    """
    try:
        with engine.connect() as connection:
            admin_count = connection.execute(
                text("SELECT COUNT(*) FROM administrators")
            ).scalar_one()
            device_count = connection.execute(
                text("SELECT COUNT(*) FROM devices WHERE status = 'ACTIVE'")
            ).scalar_one()
    except SQLAlchemyError:
        return ReadinessCheck(name="credentials", ok=False, detail="credential store unavailable")
    if int(admin_count) == 0:
        return ReadinessCheck(
            name="credentials", ok=False, detail="pilot not bootstrapped (no administrator)"
        )
    if int(device_count) == 0:
        return ReadinessCheck(
            name="credentials", ok=False, detail="pilot not bootstrapped (no registered device)"
        )
    return ReadinessCheck(name="credentials", ok=True, detail="ok")


def compute_readiness(engine: Engine, storage: ObjectStorage) -> ReadinessResult:
    """Run every probe against the live dependencies."""
    return ReadinessResult(
        checks=(probe_database(engine), probe_object_store(storage), probe_credentials(engine))
    )
