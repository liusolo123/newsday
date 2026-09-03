"""Create public news pool.

Revision ID: 20260903_02
Revises: 20260903_01
"""
from alembic import op
import sqlalchemy as sa

revision = "20260903_02"
down_revision = "20260903_01"
branch_labels = None
depends_on = None

def upgrade() -> None:
    uuid = sa.Uuid()
    op.create_table("news_items", sa.Column("id", uuid, primary_key=True), sa.Column("source", sa.String(80), nullable=False), sa.Column("canonical_url", sa.Text(), nullable=False), sa.Column("url_hash", sa.String(64), nullable=False, unique=True), sa.Column("title", sa.Text(), nullable=False), sa.Column("summary_zh", sa.Text(), nullable=False), sa.Column("category", sa.String(32), nullable=False), sa.Column("tags", sa.JSON(), nullable=False), sa.Column("score", sa.Integer(), nullable=False), sa.Column("published_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_news_items_category_published", "news_items", ["category", "published_at"])
    op.create_table("news_polishes", sa.Column("id", uuid, primary_key=True), sa.Column("news_item_id", uuid, nullable=False), sa.Column("model", sa.String(80), nullable=False), sa.Column("prompt_version", sa.String(32), nullable=False), sa.Column("content_zh", sa.Text(), nullable=False), sa.Column("usage_json", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["news_item_id"], ["news_items.id"], ondelete="CASCADE"), sa.UniqueConstraint("news_item_id", "prompt_version", name="uq_news_polishes_prompt_version"))

def downgrade() -> None:
    op.drop_table("news_polishes")
    op.drop_index("ix_news_items_category_published", table_name="news_items")
    op.drop_table("news_items")
