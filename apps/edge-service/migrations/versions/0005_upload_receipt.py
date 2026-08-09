"""upload task verified receipt columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Verified receipt metadata (design 13.3/13.4, PR-017 F5): a task may only
    # become SUCCEEDED after the central server returns a receipt whose
    # idempotency key, object, byte size, and checksum match; the verified
    # receipt and central object identifier are persisted for retention gating.
    op.add_column(
        "upload_tasks", sa.Column("central_object_id", sa.String(length=256), nullable=True)
    )
    op.add_column("upload_tasks", sa.Column("receipt_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("upload_tasks", "receipt_json")
    op.drop_column("upload_tasks", "central_object_id")
