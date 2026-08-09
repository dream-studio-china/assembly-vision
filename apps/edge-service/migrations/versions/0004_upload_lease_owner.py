"""upload task lease owner token

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fencing token for the upload worker (design 13.3, PR-017 F3): every
    # terminal or retry update must carry the per-claim token, so a late worker
    # whose lease was reclaimed can never overwrite a newer worker's state.
    op.add_column("upload_tasks", sa.Column("lease_owner", sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column("upload_tasks", "lease_owner")
