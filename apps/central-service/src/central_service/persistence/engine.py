"""SQLAlchemy engine factory for the central PostgreSQL database."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine


def create_database_engine(database_url: str) -> Engine:
    """Return an engine for the central database.

    ``pool_pre_ping`` revalidates stale pooled connections so a temporary
    PostgreSQL outage does not surface as phantom connection failures on the
    next request.
    """
    return create_engine(database_url, pool_pre_ping=True)
