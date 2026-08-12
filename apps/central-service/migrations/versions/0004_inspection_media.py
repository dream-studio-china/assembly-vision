"""media binding tables: inspection_media.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-12

C2b media ingestion: the inspection_media binding row records the edge
source media identity, its object-store key and stable central object
identifier, and the verified size/checksum. Media bytes live only in the
object store under a central generated opaque key; a row reports AVAILABLE
only after the final object exists and is checksum-verified (C1 invariant 8).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inspection_media",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_row_id",
            sa.Integer(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "inspection_row_id",
            sa.BigInteger(),
            sa.ForeignKey("inspections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_media_id", sa.String(length=36), nullable=False),
        sa.Column("media_kind", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=256), nullable=False),
        sa.Column("central_object_id", sa.String(length=36), nullable=False),
        sa.Column("lifecycle", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("capture_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "device_row_id", "source_media_id", name="uq_inspection_media_device_media"
        ),
        sa.UniqueConstraint("object_key", name="uq_inspection_media_object_key"),
        sa.UniqueConstraint("central_object_id", name="uq_inspection_media_central_object"),
    )
    op.create_index("ix_inspection_media_inspection", "inspection_media", ["inspection_row_id"])
    op.create_index("ix_inspection_media_device", "inspection_media", ["device_row_id"])
    op.create_index("ix_inspection_media_lifecycle", "inspection_media", ["lifecycle"])


def downgrade() -> None:
    op.drop_index("ix_inspection_media_lifecycle", table_name="inspection_media")
    op.drop_index("ix_inspection_media_device", table_name="inspection_media")
    op.drop_index("ix_inspection_media_inspection", table_name="inspection_media")
    op.drop_table("inspection_media")
