"""Privacy-preserving rate-limit and administrator-audit models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedUpdatedAt, UUIDPrimaryKey


class RateLimitEvent(UUIDPrimaryKey, Base):
    __tablename__ = "rate_limit_events"
    __table_args__ = (
        Index("ix_rate_limit_events_lookup", "action", "identifier_hash", "created_at"),
    )

    action: Mapped[str] = mapped_column(String(32), nullable=False)
    identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    __tablename__ = "audit_events"

    actor_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
