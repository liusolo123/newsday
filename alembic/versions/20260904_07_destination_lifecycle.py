"""Retain safe destination display state after credential deletion.

Revision ID: 20260904_07
Revises: 20260903_06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904_07"
down_revision = "20260903_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "destinations",
        sa.Column("webhook_masked", sa.String(length=256), nullable=False, server_default=""),
    )
    op.add_column("destinations", sa.Column("credential_deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("destinations", "credential_deleted_at")
    op.drop_column("destinations", "webhook_masked")
