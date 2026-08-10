"""Alembic migration runner for the central PostgreSQL schema (C1a).

Migrations are a controlled release step: the API process never applies them
automatically. Operators run ``python -m central_service migrate`` once per
deployment, then the API reports readiness only when the applied revision
matches the script head.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from central_service.persistence.engine import create_database_engine

# ``AV_CENTRAL_ROOT`` lets a packaged deployment point at the directory that
# carries ``alembic.ini`` and ``migrations/`` when the package is installed
# non-editable; the source-tree default keeps local runs unchanged.
_CENTRAL_ROOT = Path(os.environ.get("AV_CENTRAL_ROOT", str(Path(__file__).resolve().parents[3])))
_ALEMBIC_INI = _CENTRAL_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _CENTRAL_ROOT / "migrations"


def _config(database_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def current_head() -> str:
    """Return the Alembic head revision of the central schema scripts."""
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if head is None:
        raise RuntimeError("no alembic head revision found for the central schema")
    return head


def applied_revision(engine: Engine) -> str | None:
    """Return the applied Alembic revision, or None when not migrated."""
    try:
        with engine.connect() as connection:
            row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
    except SQLAlchemyError:
        return None
    return str(row[0]) if row is not None else None


def schema_at_head(database_url: str) -> bool:
    """Return whether the database is at the script head revision."""
    engine = create_database_engine(database_url)
    try:
        applied = applied_revision(engine)
    finally:
        engine.dispose()
    return applied == current_head()


def migrate_to_head(database_url: str) -> None:
    """Apply all pending migrations and leave the database at the head."""
    command.upgrade(_config(database_url), "head")
