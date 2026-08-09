"""media retention and deletion coordination fields

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Retention/deletion coordination state (design 12.6/12.7, E2 task). The
    # filesystem holds media bytes; SQLite holds metadata and the deletion
    # state machine. A PURGED row remains an audit tombstone. Existing rows get
    # NULL retention_eligible_at and are therefore protected (never eligible).
    op.add_column("media", sa.Column("created_at", sa.Text(), nullable=True))
    op.add_column("media", sa.Column("retention_eligible_at", sa.Text(), nullable=True))
    op.add_column("media", sa.Column("hold_reason", sa.String(length=128), nullable=True))
    op.add_column("media", sa.Column("deleting_at", sa.Text(), nullable=True))
    op.add_column("media", sa.Column("delete_lease_owner", sa.String(length=36), nullable=True))
    op.add_column("media", sa.Column("delete_lease_expires_at", sa.Text(), nullable=True))
    op.add_column("media", sa.Column("purged_at", sa.Text(), nullable=True))
    op.add_column("media", sa.Column("purge_reason", sa.String(length=64), nullable=True))
    op.add_column("media", sa.Column("last_delete_error", sa.String(length=256), nullable=True))
    op.add_column("media", sa.Column("integrity_status", sa.String(length=16), nullable=True))
    op.create_index("ix_media_retention", "media", ["lifecycle", "retention_eligible_at"])


def downgrade() -> None:
    op.drop_index("ix_media_retention", table_name="media")
    op.drop_column("media", "integrity_status")
    op.drop_column("media", "last_delete_error")
    op.drop_column("media", "purge_reason")
    op.drop_column("media", "purged_at")
    op.drop_column("media", "delete_lease_expires_at")
    op.drop_column("media", "delete_lease_owner")
    op.drop_column("media", "deleting_at")
    op.drop_column("media", "hold_reason")
    op.drop_column("media", "retention_eligible_at")
    op.drop_column("media", "created_at")
