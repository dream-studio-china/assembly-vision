"""upload task lease column

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lease column for the upload worker (design 13.3): a crashed worker's
    # IN_PROGRESS task is reclaimed once its lease expires instead of being
    # stuck forever.
    op.add_column("upload_tasks", sa.Column("lease_expires_at", sa.Text(), nullable=True))
    op.create_index("ix_upload_tasks_due", "upload_tasks", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_upload_tasks_due", table_name="upload_tasks")
    op.drop_column("upload_tasks", "lease_expires_at")
