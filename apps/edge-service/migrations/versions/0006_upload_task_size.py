"""upload task payload size for queue metrics

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Payload size per task so device status can report queue bytes and oldest
    # pending age without reading media files (design 13.9, E1 observability).
    op.add_column("upload_tasks", sa.Column("size_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("upload_tasks", "size_bytes")
