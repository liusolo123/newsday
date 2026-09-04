"""Add a non-sensitive administrator note for invitation codes.

Revision ID: 20260904_11
Revises: 20260904_10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904_11"
down_revision = "20260904_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invite_codes",
        sa.Column("admin_note", sa.String(length=120), nullable=False, server_default=""),
    )
    op.alter_column("invite_codes", "admin_note", server_default=None)


def downgrade() -> None:
    op.drop_column("invite_codes", "admin_note")
