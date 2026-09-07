"""Add durable public-news selection batches.

Revision ID: 20260907_12
Revises: 20260904_11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260907_12"
down_revision = "20260904_11"
branch_labels = None
depends_on = None


PUBLICATION_CATEGORIES = (
    "all",
    "ai",
    "technology",
    "consumer_electronics",
    "github",
    "business",
    "markets",
    "politics",
    "sports",
    "entertainment",
    "social_trends",
)


def _in_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    uuid = sa.Uuid()
    op.create_table(
        "public_news_batches",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="selecting"),
        sa.Column(
            "selection_policy_version", sa.String(length=32), nullable=False, server_default="public-v1"
        ),
        sa.Column("prompt_version", sa.String(length=32), nullable=False, server_default="summary-v2"),
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("deficits", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('selecting', 'polishing', 'ready', 'published', 'failed')",
            name="ck_public_news_batches_status",
        ),
        sa.CheckConstraint("target_count BETWEEN 1 AND 10", name="ck_public_news_batches_target_count"),
    )
    op.create_index("ix_public_news_batches_status", "public_news_batches", ["status"])
    op.create_table(
        "public_news_selections",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("batch_id", uuid, nullable=False),
        sa.Column("news_item_id", uuid, nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("selection_reason", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("polish_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "category IN (" + _in_values(PUBLICATION_CATEGORIES) + ")",
            name="ck_public_news_selections_category",
        ),
        sa.CheckConstraint("position BETWEEN 1 AND 10", name="ck_public_news_selections_position"),
        sa.CheckConstraint(
            "polish_status IN ('pending', 'succeeded', 'failed')",
            name="ck_public_news_selections_polish_status",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["public_news_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["news_item_id"], ["news_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "category", "news_item_id", name="uq_public_news_selections_news"),
        sa.UniqueConstraint("batch_id", "category", "position", name="uq_public_news_selections_position"),
    )
    op.create_index(
        "ix_public_news_selections_batch_category",
        "public_news_selections",
        ["batch_id", "category"],
    )
    op.create_index("ix_public_news_selections_news_item_id", "public_news_selections", ["news_item_id"])


def downgrade() -> None:
    op.drop_index("ix_public_news_selections_news_item_id", table_name="public_news_selections")
    op.drop_index("ix_public_news_selections_batch_category", table_name="public_news_selections")
    op.drop_table("public_news_selections")
    op.drop_index("ix_public_news_batches_status", table_name="public_news_batches")
    op.drop_table("public_news_batches")
