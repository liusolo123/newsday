"""Subscription choices, schedules, and encrypted destinations."""

from __future__ import annotations

from datetime import datetime, time
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedUpdatedAt, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.models.user import User


CATEGORY_VALUES = (
    "ai", "technology", "consumer_electronics", "github", "business", "markets",
    "politics", "sports", "entertainment", "social_trends",
)


class Subscription(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    user: Mapped[User] = relationship(back_populates="subscription")
    categories: Mapped[list[SubscriptionCategory]] = relationship(back_populates="subscription", cascade="all, delete-orphan")
    schedules: Mapped[list[Schedule]] = relationship(back_populates="subscription", cascade="all, delete-orphan")
    destinations: Mapped[list[Destination]] = relationship(back_populates="subscription", cascade="all, delete-orphan")


class SubscriptionCategory(UUIDPrimaryKey, Base):
    __tablename__ = "subscription_categories"
    __table_args__ = (
        UniqueConstraint("subscription_id", "category", name="uq_subscription_categories_category"),
        CheckConstraint("item_limit BETWEEN 5 AND 10", name="ck_subscription_categories_item_limit"),
        CheckConstraint("category IN (" + ", ".join(f"'{value}'" for value in CATEGORY_VALUES) + ")", name="ck_subscription_categories_category"),
    )

    subscription_id: Mapped[UUID] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    item_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    subscription: Mapped[Subscription] = relationship(back_populates="categories")


class Schedule(UUIDPrimaryKey, Base):
    __tablename__ = "schedules"
    __table_args__ = (UniqueConstraint("subscription_id", "local_time", name="uq_schedules_local_time"),)

    subscription_id: Mapped[UUID] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    local_time: Mapped[time] = mapped_column(Time, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    subscription: Mapped[Subscription] = relationship(back_populates="schedules")


class Destination(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    __tablename__ = "destinations"
    __table_args__ = (CheckConstraint("kind IN ('feishu', 'wecom')", name="ck_destinations_kind"),)

    subscription_id: Mapped[UUID] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    webhook_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    webhook_nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription: Mapped[Subscription] = relationship(back_populates="destinations")
