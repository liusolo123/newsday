"""Create rate-limit and administrator audit tables.

Revision ID: 20260903_06
Revises: 20260903_05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260903_06"
down_revision = "20260903_05"
branch_labels = None
depends_on = None


def upgrade():
    uuid = sa.Uuid()
    op.create_table(
        "rate_limit_events",
        sa.Column("id", uuid, nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rate_limit_events_lookup",
        "rate_limit_events",
        ["action", "identifier_hash", "created_at"],
    )
    op.create_table(
        "audit_events",
        sa.Column("id", uuid, nullable=False),
        sa.Column("actor_user_id", uuid, nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("audit_events")
    op.drop_index("ix_rate_limit_events_lookup", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
