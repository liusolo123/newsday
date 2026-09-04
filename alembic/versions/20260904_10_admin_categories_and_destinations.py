"""Add managed category presets and reversible destination controls.

Revision ID: 20260904_10
Revises: 20260904_09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904_10"
down_revision = "20260904_09"
branch_labels = None
depends_on = None


PRESETS = [
    ("ai", "AI", "AI", 10),
    ("technology", "科技", "Technology", 20),
    ("consumer_electronics", "消费电子", "Consumer electronics", 30),
    ("github", "GitHub", "GitHub", 40),
    ("business", "财经", "Business", 50),
    ("markets", "投资市场", "Markets", 60),
    ("politics", "时政", "Politics", 70),
    ("sports", "体育", "Sports", 80),
    ("entertainment", "娱乐", "Entertainment", 90),
    ("social_trends", "社会热搜", "Social trends", 100),
]


def upgrade() -> None:
    op.create_table(
        "category_presets",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("label_zh", sa.String(length=64), nullable=False),
        sa.Column("label_en", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.bulk_insert(
        sa.table(
            "category_presets",
            sa.column("key", sa.String),
            sa.column("label_zh", sa.String),
            sa.column("label_en", sa.String),
            sa.column("enabled", sa.Boolean),
            sa.column("sort_order", sa.Integer),
        ),
        [
            {"key": key, "label_zh": zh, "label_en": en, "enabled": True, "sort_order": order}
            for key, zh, en, order in PRESETS
        ],
    )
    op.add_column(
        "destinations", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true())
    )


def downgrade() -> None:
    op.drop_column("destinations", "enabled")
    op.drop_table("category_presets")
