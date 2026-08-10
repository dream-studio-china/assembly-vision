"""append-only human review records

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Append-only human review dispositions (design 24.7). Records snapshot the
    # original machine outcome so a review stays interpretable if the
    # inspection projection is later purged; corrections supersede by
    # reference instead of overwriting.
    op.create_table(
        "review_records",
        sa.Column("review_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "inspection_id",
            sa.String(length=36),
            sa.ForeignKey("inspections.inspection_id"),
            nullable=False,
        ),
        sa.Column("disposition", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("original_business_result", sa.String(length=16), nullable=False),
        sa.Column("original_internal_decision", sa.String(length=16), nullable=False),
        sa.Column("original_reason_codes", sa.Text(), nullable=False),
        sa.Column("component_corrections", sa.Text(), nullable=True),
        sa.Column("supersedes_review_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_review_records_inspection",
        "review_records",
        ["inspection_id", "created_at"],
    )
    op.create_index("ix_review_records_created_at", "review_records", ["created_at"])
    op.create_index("ix_review_records_disposition", "review_records", ["disposition"])


def downgrade() -> None:
    op.drop_index("ix_review_records_disposition", table_name="review_records")
    op.drop_index("ix_review_records_created_at", table_name="review_records")
    op.drop_index("ix_review_records_inspection", table_name="review_records")
    op.drop_table("review_records")
