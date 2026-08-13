"""add canonical request hash to review records.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-13

C4 hardening: bind each review idempotency key to the canonical hash of the
submitted request so a reused key with different content is an explicit
conflict rather than a silent replay. Existing rows carry NULL; new appends
always write the hash.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "review_records",
        sa.Column("request_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_records", "request_hash")
