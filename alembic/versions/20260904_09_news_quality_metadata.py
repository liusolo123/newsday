"""Store reviewable content-quality and verification metadata.

Revision ID: 20260904_09
Revises: 20260904_08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904_09"
down_revision = "20260904_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news_items",
        sa.Column("title_similarity_key", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "news_items",
        sa.Column("title_similarity_tokens", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "news_items",
        sa.Column("source_trust", sa.String(length=24), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "news_items",
        sa.Column(
            "verification_status", sa.String(length=32), nullable=False, server_default="unverified"
        ),
    )
    op.add_column(
        "news_items",
        sa.Column("corroborating_sources", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index(
        "ix_news_items_title_similarity_key", "news_items", ["title_similarity_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_news_items_title_similarity_key", table_name="news_items")
    op.drop_column("news_items", "corroborating_sources")
    op.drop_column("news_items", "verification_status")
    op.drop_column("news_items", "source_trust")
    op.drop_column("news_items", "title_similarity_tokens")
    op.drop_column("news_items", "title_similarity_key")
