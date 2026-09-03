"""Add indexes used by scheduling, retries, and delivery history queries.

Revision ID: 20260904_08
Revises: 20260904_07
"""

from alembic import op


revision = "20260904_08"
down_revision = "20260904_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_delivery_jobs_status_next_attempt",
        "delivery_jobs",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_delivery_jobs_status_scheduled",
        "delivery_jobs",
        ["status", "scheduled_for"],
    )
    op.create_index(
        "ix_delivery_jobs_subscription_scheduled",
        "delivery_jobs",
        ["subscription_id", "scheduled_for"],
    )
    op.create_index("ix_delivery_attempts_job", "delivery_attempts", ["delivery_job_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_attempts_job", table_name="delivery_attempts")
    op.drop_index("ix_delivery_jobs_subscription_scheduled", table_name="delivery_jobs")
    op.drop_index("ix_delivery_jobs_status_scheduled", table_name="delivery_jobs")
    op.drop_index("ix_delivery_jobs_status_next_attempt", table_name="delivery_jobs")
