"""initial edge schema

Revision ID: 0001
Revises:
Create Date: 2026-08-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inspections",
        sa.Column("inspection_id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("device_sequence", sa.Integer(), nullable=False),
        sa.Column("lifecycle_status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text(), nullable=False),
        sa.Column("barcode_result", sa.Text(), nullable=False),
        sa.Column("product_resolution", sa.Text(), nullable=False),
        sa.Column("product_detection", sa.Text(), nullable=True),
        sa.Column("roi_result", sa.Text(), nullable=True),
        sa.Column("frame_quality_summary", sa.Text(), nullable=False),
        sa.Column("application_version", sa.String(64), nullable=False),
        sa.Column("product_model_version_id", sa.String(36), nullable=False),
        sa.Column("product_model_checksum_sha256", sa.String(64), nullable=False),
        sa.Column("component_model_version_id", sa.String(36), nullable=False),
        sa.Column("component_model_checksum_sha256", sa.String(64), nullable=False),
        sa.Column("rule_version_id", sa.String(36), nullable=False),
        sa.Column("aggregation_policy_version", sa.String(64), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("synchronization_status", sa.String(32), nullable=False),
        sa.Column("processing_ms", sa.Integer(), nullable=False),
        sa.Column("inference_metadata", sa.Text(), nullable=True),
        sa.Column("business_result", sa.String(16), nullable=False),
        sa.Column("internal_decision", sa.String(16), nullable=False),
        sa.Column("barcode_value", sa.String(256), nullable=True),
        sa.Column("product_code", sa.String(128), nullable=True),
    )
    op.create_index("ix_inspections_completed_at", "inspections", ["completed_at"])
    op.create_index("ix_inspections_business_result", "inspections", ["business_result"])
    op.create_index("ix_inspections_internal_decision", "inspections", ["internal_decision"])
    op.create_index("ix_inspections_barcode_value", "inspections", ["barcode_value"])
    op.create_index("ix_inspections_product_code", "inspections", ["product_code"])
    op.create_index("ix_inspections_device_id", "inspections", ["device_id"])
    op.create_index("ix_inspections_model_version", "inspections", ["product_model_version_id"])
    op.create_index("ix_inspections_sync_status", "inspections", ["synchronization_status"])

    op.create_table(
        "component_evidence",
        sa.Column("evidence_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("inspection_id", sa.String(36), nullable=False),
        sa.Column("component_code", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("best_confidence", sa.Float(), nullable=True),
        sa.Column("usable_frame_count", sa.Integer(), nullable=False),
        sa.Column("detection_count", sa.Integer(), nullable=False),
        sa.Column("adjacent_detection_run", sa.Integer(), nullable=False),
        sa.Column("supporting_frame_ids", sa.JSON(), nullable=False),
        sa.Column("policy_reason_codes", sa.JSON(), nullable=False),
        sa.Column("box_area_ratios", sa.JSON(), nullable=False),
        sa.Column("box_centers", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["inspection_id"], ["inspections.inspection_id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "media",
        sa.Column("media_id", sa.String(36), primary_key=True),
        sa.Column("inspection_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("lifecycle", sa.String(16), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["inspection_id"], ["inspections.inspection_id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "upload_tasks",
        sa.Column("upload_task_id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("inspection_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(36), nullable=False),
        sa.Column("payload_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text(), nullable=True),
    )
    op.create_index("ix_upload_tasks_status", "upload_tasks", ["status"])
    op.create_index("ix_upload_tasks_inspection", "upload_tasks", ["inspection_id"])

    op.create_table(
        "device_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.String(512), nullable=False),
    )

    op.create_table(
        "active_packages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("model_version_id", sa.String(36), nullable=False),
        sa.Column("semantic_version", sa.String(64), nullable=True),
        sa.Column("rule_version_id", sa.String(36), nullable=True),
        sa.Column("installed_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("active_packages")
    op.drop_table("device_events")
    op.drop_table("upload_tasks")
    op.drop_table("media")
    op.drop_table("component_evidence")
    op.drop_table("inspections")
