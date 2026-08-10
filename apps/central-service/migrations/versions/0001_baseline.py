"""baseline: establish the central_meta marker table.

Revision ID: 0001
Revises:
Create Date: 2026-08-11

Tenant, device, ingestion, review, and governance tables arrive in later
migrations (C1b/C2a/C2b/C4/C5). ``central_meta`` anchors the required-schema
readiness check until then.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "central_meta",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=256), nullable=False),
    )
    op.execute("INSERT INTO central_meta (key, value) VALUES ('schema_version', '1')")


def downgrade() -> None:
    op.drop_table("central_meta")
