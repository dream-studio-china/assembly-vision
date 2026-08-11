"""pilot tenant, device, and credential tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11

C1b tenant/device/credential foundation: organizations, sites,
production_lines, devices (hashed upload credentials), pilot administrators,
their browser sessions, and a minimum audit log. Ingestion (C2a), media
(C2b), review (C4), and governance (C5) tables arrive in later migrations.

Production lines and devices use composite foreign keys that bind
``organization_id`` to the organization of their referenced site/line so a
row can never reference another tenant's hierarchy node; every tenant-owned
row, including admin sessions, carries ``organization_id``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "name", name="uq_sites_organization_name"),
        sa.UniqueConstraint("id", "organization_id", name="uq_sites_id_organization"),
    )

    op.create_table(
        "production_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("site_id", "name", name="uq_production_lines_site_name"),
        sa.UniqueConstraint("id", "organization_id", name="uq_production_lines_id_organization"),
        sa.ForeignKeyConstraint(
            ["organization_id", "site_id"],
            ["sites.id", "sites.organization_id"],
            name="fk_production_lines_site_organization",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("production_line_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column("upload_token_hash", sa.String(length=128), nullable=False),
        sa.Column("upload_token_salt", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "device_id", name="uq_devices_organization_device"),
        sa.ForeignKeyConstraint(
            ["organization_id", "site_id"],
            ["sites.id", "sites.organization_id"],
            name="fk_devices_site_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "production_line_id"],
            ["production_lines.id", "production_lines.organization_id"],
            name="fk_devices_line_organization",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "administrators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("token_salt", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "organization_id", "username", name="uq_administrators_organization_username"
        ),
    )

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "administrator_id",
            sa.Integer(),
            sa.ForeignKey("administrators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_lookup", sa.String(length=32), nullable=False, unique=True),
        sa.Column("session_token_hash", sa.String(length=128), nullable=False),
        sa.Column("session_token_salt", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("ix_devices_organization", "devices", ["organization_id"])
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])
    op.create_index("ix_admin_sessions_organization", "admin_sessions", ["organization_id"])
    op.create_index(
        "ix_audit_organization_created",
        "audit_logs",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_organization_created", table_name="audit_logs")
    op.drop_index("ix_admin_sessions_organization", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_expires_at", table_name="admin_sessions")
    op.drop_index("ix_devices_organization", table_name="devices")
    op.drop_table("audit_logs")
    op.drop_table("admin_sessions")
    op.drop_table("administrators")
    op.drop_table("devices")
    op.drop_table("production_lines")
    op.drop_table("sites")
    op.drop_table("organizations")
