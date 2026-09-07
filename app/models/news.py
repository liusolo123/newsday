"""Public news pool and cached Chinese polishing records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedUpdatedAt, UUIDPrimaryKey
from app.models.subscription import CATEGORY_VALUES


PUBLICATION_STATUS_VALUES = ("selecting", "polishing", "ready", "published", "failed")
PUBLICATION_POLISH_STATUS_VALUES = ("pending", "succeeded", "failed")
PUBLICATION_CATEGORY_VALUES = ("all", *CATEGORY_VALUES)


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
    publication_selections: Mapped[list[PublicNewsSelection]] = relationship(
        back_populates="news_item", cascade="all, delete-orphan"
    )


class NewsPolish(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    __tablename__ = "news_polishes"
    __table_args__ = (UniqueConstraint("news_item_id", "prompt_version", name="uq_news_polishes_prompt_version"),)

    news_item_id: Mapped[object] = mapped_column(ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_zh: Mapped[str] = mapped_column(Text, nullable=False)
    usage_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    news_item: Mapped[NewsItem] = relationship(back_populates="polishes")


class PublicNewsBatch(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    """A frozen candidate set that becomes public only after later workflow checks."""

    __tablename__ = "public_news_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{value}'" for value in PUBLICATION_STATUS_VALUES) + ")",
            name="ck_public_news_batches_status",
        ),
        CheckConstraint("target_count BETWEEN 1 AND 10", name="ck_public_news_batches_target_count"),
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="selecting", index=True)
    selection_policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="public-v1")
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="summary-v2")
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    deficits: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    selections: Mapped[list[PublicNewsSelection]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class PublicNewsSelection(UUIDPrimaryKey, CreatedUpdatedAt, Base):
    """One ranked news item in a public batch and category, including the All feed."""

    __tablename__ = "public_news_selections"
    __table_args__ = (
        UniqueConstraint("batch_id", "category", "news_item_id", name="uq_public_news_selections_news"),
        UniqueConstraint("batch_id", "category", "position", name="uq_public_news_selections_position"),
        CheckConstraint(
            "category IN (" + ", ".join(f"'{value}'" for value in PUBLICATION_CATEGORY_VALUES) + ")",
            name="ck_public_news_selections_category",
        ),
        CheckConstraint("position BETWEEN 1 AND 10", name="ck_public_news_selections_position"),
        CheckConstraint(
            "polish_status IN ("
            + ", ".join(f"'{value}'" for value in PUBLICATION_POLISH_STATUS_VALUES)
            + ")",
            name="ck_public_news_selections_polish_status",
        ),
        Index("ix_public_news_selections_batch_category", "batch_id", "category"),
    )

    batch_id: Mapped[object] = mapped_column(
        ForeignKey("public_news_batches.id", ondelete="CASCADE"), nullable=False
    )
    news_item_id: Mapped[object] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_reason: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    polish_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    batch: Mapped[PublicNewsBatch] = relationship(back_populates="selections")
    news_item: Mapped[NewsItem] = relationship(back_populates="publication_selections")
