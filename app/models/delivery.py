"""Durable, idempotent delivery jobs and their immutable selected items."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, CreatedUpdatedAt, UUIDPrimaryKey

class DeliveryJob(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    __tablename__ = "delivery_jobs"
    __table_args__ = (UniqueConstraint("subscription_id", "destination_id", "scheduled_for", name="uq_delivery_jobs_schedule"),)
    subscription_id: Mapped[UUID] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    destination_id: Mapped[UUID] = mapped_column(ForeignKey("destinations.id", ondelete="CASCADE"), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

class DeliveryItem(UUIDPrimaryKey, Base):
    __tablename__ = "delivery_items"
    __table_args__ = (UniqueConstraint("delivery_job_id", "news_item_id", name="uq_delivery_items_news"),)
    delivery_job_id: Mapped[UUID] = mapped_column(ForeignKey("delivery_jobs.id", ondelete="CASCADE"), nullable=False)
    news_item_id: Mapped[UUID] = mapped_column(ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

class DeliveryAttempt(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    __tablename__ = "delivery_attempts"
    delivery_job_id: Mapped[UUID] = mapped_column(ForeignKey("delivery_jobs.id", ondelete="CASCADE"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
