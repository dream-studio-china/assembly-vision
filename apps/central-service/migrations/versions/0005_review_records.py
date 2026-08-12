"""review tables: review_records.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-12

C4 central append-only human review: per-inspection revision chains with the
original machine decision snapshotted on every record. Revisions append and
never overwrite; idempotency keys make client retries duplicate-free.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "inspection_row_id",
            sa.BigInteger(),
            sa.ForeignKey("inspections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column("reviewer", sa.String(length=128), nullable=False),
        sa.Column("component_corrections", sa.JSON(), nullable=True),
        sa.Column("original_business_result", sa.String(length=8), nullable=False),
        sa.Column("original_internal_decision", sa.String(length=16), nullable=False),
        sa.Column("original_reason_codes", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "inspection_row_id", "revision", name="uq_review_records_inspection_revision"
        ),
        sa.UniqueConstraint(
            "inspection_row_id", "idempotency_key", name="uq_review_records_inspection_key"
        ),
    )
    op.create_index(
        "ix_review_records_inspection",
        "review_records",
        ["inspection_row_id", "revision"],
    )
    op.create_index(
        "ix_review_records_created",
        "review_records",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_records_created", table_name="review_records")
    op.drop_index("ix_review_records_inspection", table_name="review_records")
    op.drop_table("review_records")
