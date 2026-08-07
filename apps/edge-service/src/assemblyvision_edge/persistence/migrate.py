"""Alembic migration runner for the edge SQLite database."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_EDGE_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _EDGE_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _EDGE_ROOT / "migrations"


def migrate_to_head(sqlite_path: str) -> None:
    """Run all pending Alembic migrations against a SQLite database."""
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{sqlite_path}")
    command.upgrade(cfg, "head")
