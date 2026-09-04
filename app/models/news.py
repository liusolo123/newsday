"""Public news pool and cached Chinese polishing records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedUpdatedAt, UUIDPrimaryKey


class NewsItem(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    __tablename__ = "news_items"

    source: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary_zh: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    title_similarity_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title_similarity_tokens: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_trust: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unverified")
    corroborating_sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    polishes: Mapped[list[NewsPolish]] = relationship(back_populates="news_item", cascade="all, delete-orphan")


class NewsPolish(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    __tablename__ = "news_polishes"
    __table_args__ = (UniqueConstraint("news_item_id", "prompt_version", name="uq_news_polishes_prompt_version"),)

    news_item_id: Mapped[object] = mapped_column(ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_zh: Mapped[str] = mapped_column(Text, nullable=False)
    usage_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    news_item: Mapped[NewsItem] = relationship(back_populates="polishes")
