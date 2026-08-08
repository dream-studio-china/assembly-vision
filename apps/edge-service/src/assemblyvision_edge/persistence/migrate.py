"""Alembic migration runner for the edge SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

_EDGE_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _EDGE_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _EDGE_ROOT / "migrations"


def migrate_to_head(sqlite_path: str) -> None:
    """Run all pending Alembic migrations and verify the database is at head.

    A successful migration run must leave the database at the script head; any
    mismatch (e.g. a partially applied or manually modified schema) fails
    startup rather than serving a partially migrated read index (C4).
    """
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{sqlite_path}")
    head = ScriptDirectory.from_config(cfg).get_current_head()
    command.upgrade(cfg, "head")
    _verify_revision(sqlite_path, head)


def _verify_revision(sqlite_path: str, expected: str | None) -> None:
    if expected is None:
        raise RuntimeError("no alembic head revision found for the edge schema")
    try:
        conn = sqlite3.connect(sqlite_path)
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot read edge database migration state: {exc}") from exc
    if row is None or row[0] != expected:
        raise RuntimeError(
            f"edge database is at migration {row[0] if row else 'none'}; expected {expected}"
        )
