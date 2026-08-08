"""rule identity registry

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_identities",
        sa.Column("rule_id", sa.String(128), primary_key=True),
        sa.Column("rule_version", sa.Integer(), primary_key=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("registered_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rule_identities")
