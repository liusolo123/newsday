"""Retain raw source material for delivery-time polishing.

Revision ID: 20260903_03
Revises: 20260903_02
"""
from alembic import op
import sqlalchemy as sa
revision = "20260903_03"
down_revision = "20260903_02"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.add_column("news_items", sa.Column("source_summary", sa.Text(), nullable=False, server_default=""))
def downgrade() -> None:
    op.drop_column("news_items", "source_summary")
