"""Central pilot schema defined as SQLAlchemy Core tables (C1b).

The table set implements docs/tasks/C1-central-server-m1.md section 8.1 for
the tenant/device/credential domain: organizations, sites, production_lines,
devices (with hashed upload credentials), pilot administrators, their browser
sessions, and a minimum audit log. The Alembic migrations under
``apps/central-service/migrations/`` mirror these definitions for PostgreSQL;
tests create the same schema through ``metadata.create_all`` on SQLite.

Tenant-hierarchy integrity is enforced in the database: production lines and
devices carry composite foreign keys that bind their ``organization_id`` to
the organization of their referenced site/line, so a row can never reference
another tenant's hierarchy node.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

metadata = MetaData()

# Audit logs can grow far beyond pilot scale on PostgreSQL, while SQLite test
# databases need the exact INTEGER type for a rowid-alias primary key.
_BigIntId = BigInteger().with_variant(Integer, "sqlite")

_UTC_NOW = func.now()

organizations = Table(
    "organizations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(128), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
)

sites = Table(
    "sites",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "name", name="uq_sites_organization_name"),
    # Referenced by the composite site foreign keys on production_lines and
    # devices, which bind organization_id to the referenced site's tenant.
    UniqueConstraint("id", "organization_id", name="uq_sites_id_organization"),
)

production_lines = Table(
    "production_lines",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("site_id", Integer, nullable=False),
    Column("name", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("site_id", "name", name="uq_production_lines_site_name"),
    UniqueConstraint("id", "organization_id", name="uq_production_lines_id_organization"),
    ForeignKeyConstraint(
        ["organization_id", "site_id"],
        ["sites.id", "sites.organization_id"],
        name="fk_production_lines_site_organization",
        ondelete="CASCADE",
    ),
)

devices = Table(
    "devices",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("site_id", Integer, nullable=False),
    Column("production_line_id", Integer, nullable=False),
    # Edge device identity (``device_id`` in the edge upload envelope); the
    # integer primary key stays internal. The edge identity is unique per
    # organization so a registration cannot collide across tenants.
    Column("device_id", String(128), nullable=False),
    Column("name", String(128), nullable=False),
    Column("status", String(16), nullable=False, server_default="ACTIVE"),
    Column("upload_token_hash", String(128), nullable=False),
    Column("upload_token_salt", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "device_id", name="uq_devices_organization_device"),
    ForeignKeyConstraint(
        ["organization_id", "site_id"],
        ["sites.id", "sites.organization_id"],
        name="fk_devices_site_organization",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["organization_id", "production_line_id"],
        ["production_lines.id", "production_lines.organization_id"],
        name="fk_devices_line_organization",
        ondelete="CASCADE",
    ),
)

administrators = Table(
    "administrators",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("username", String(128), nullable=False),
    Column("token_hash", String(128), nullable=False),
    Column("token_salt", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "username", name="uq_administrators_organization_username"),
)

admin_sessions = Table(
    "admin_sessions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "administrator_id",
        ForeignKey("administrators.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Every tenant-owned row carries organization scope (C1 invariant 6); the
    # session is validated against the administrator's organization on use.
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Public random lookup half of the session token; the secret half is only
    # ever stored hashed, so a leaked session table cannot forge a session.
    Column("session_lookup", String(32), nullable=False, unique=True),
    Column("session_token_hash", String(128), nullable=False),
    Column("session_token_salt", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", _BigIntId, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("actor_type", String(16), nullable=False),
    Column("actor_id", Integer, nullable=True),
    Column("action", String(64), nullable=False),
    Column("target_type", String(64), nullable=True),
    Column("target_id", String(64), nullable=True),
    Column("detail", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
)

Index("ix_devices_organization", devices.c.organization_id)
Index("ix_admin_sessions_expires_at", admin_sessions.c.expires_at)
Index("ix_admin_sessions_organization", admin_sessions.c.organization_id)
Index("ix_audit_organization_created", audit_logs.c.organization_id, audit_logs.c.created_at)
