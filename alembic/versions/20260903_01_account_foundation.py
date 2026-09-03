"""Create account and subscription foundation tables.

Revision ID: 20260903_01
Revises:
Create Date: 2026-09-03 14:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260903_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = sa.Uuid()
    op.create_table("users", sa.Column("id", uuid, nullable=False), sa.Column("username", sa.String(32), nullable=False), sa.Column("normalized_username", sa.String(32), nullable=False), sa.Column("password_hash", sa.String(512), nullable=False), sa.Column("recovery_code_hash", sa.String(512), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.CheckConstraint("length(username) BETWEEN 3 AND 32", name="ck_users_username_length"), sa.CheckConstraint("status IN ('active', 'suspended', 'cancelled')", name="ck_users_status"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("normalized_username"))
    op.create_table("invite_codes", sa.Column("id", uuid, nullable=False), sa.Column("lookup_hash", sa.String(64), nullable=False), sa.Column("secret_hash", sa.String(512), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("max_uses", sa.Integer(), nullable=True), sa.Column("used_count", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.CheckConstraint("used_count >= 0", name="ck_invite_codes_used_count"), sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_invite_codes_max_uses"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("lookup_hash"))
    op.create_table("subscriptions", sa.Column("id", uuid, nullable=False), sa.Column("user_id", uuid, nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("timezone", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("user_id"))
    op.create_table("auth_sessions", sa.Column("id", uuid, nullable=False), sa.Column("user_id", uuid, nullable=False), sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("token_hash"))
    op.create_table("subscription_categories", sa.Column("id", uuid, nullable=False), sa.Column("subscription_id", uuid, nullable=False), sa.Column("category", sa.String(32), nullable=False), sa.Column("item_limit", sa.Integer(), nullable=False), sa.CheckConstraint("item_limit BETWEEN 5 AND 10", name="ck_subscription_categories_item_limit"), sa.CheckConstraint("category IN ('ai', 'technology', 'consumer_electronics', 'github', 'business', 'markets', 'politics', 'sports', 'entertainment', 'social_trends')", name="ck_subscription_categories_category"), sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("subscription_id", "category", name="uq_subscription_categories_category"))
    op.create_table("schedules", sa.Column("id", uuid, nullable=False), sa.Column("subscription_id", uuid, nullable=False), sa.Column("local_time", sa.Time(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False), sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("subscription_id", "local_time", name="uq_schedules_local_time"))
    op.create_table("destinations", sa.Column("id", uuid, nullable=False), sa.Column("subscription_id", uuid, nullable=False), sa.Column("kind", sa.String(16), nullable=False), sa.Column("webhook_ciphertext", sa.Text(), nullable=False), sa.Column("webhook_nonce", sa.String(64), nullable=False), sa.Column("key_version", sa.Integer(), nullable=False), sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.CheckConstraint("kind IN ('feishu', 'wecom')", name="ck_destinations_kind"), sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))


def downgrade() -> None:
    op.drop_table("destinations")
    op.drop_table("schedules")
    op.drop_table("subscription_categories")
    op.drop_table("auth_sessions")
    op.drop_table("subscriptions")
    op.drop_table("invite_codes")
    op.drop_table("users")
