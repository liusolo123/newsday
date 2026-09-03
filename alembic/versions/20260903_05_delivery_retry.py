"""Add retry scheduling to delivery jobs.
Revision ID: 20260903_05
Revises: 20260903_04
"""
from alembic import op
import sqlalchemy as sa
revision="20260903_05"; down_revision="20260903_04"; branch_labels=None; depends_on=None
def upgrade():
    op.add_column("delivery_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
def downgrade():
    op.drop_column("delivery_jobs", "next_attempt_at")
