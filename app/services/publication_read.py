"""Read only the latest complete public-news snapshot for the web page."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import NewsItem, NewsPolish, PublicNewsBatch, PublicNewsSelection
from app.models.subscription import CATEGORY_VALUES
from app.services.polish import SUCCESSFUL_POLISH_STATUSES


@dataclass(frozen=True)
class PublicNewsDisplayItem:
    """A display-safe news record with the published summary attached."""

    source: str
    canonical_url: str
    title: str
    summary_zh: str
    category: str
    source_trust: str
    verification_status: str


@dataclass(frozen=True)
class PublishedNewsSnapshot:
    batch: PublicNewsBatch | None
    category: str
    items: tuple[PublicNewsDisplayItem, ...]
    counts: dict[str, int]


def _selected_category(category: str | None) -> str:
    return category if category in CATEGORY_VALUES else "all"


def published_public_news(session: Session, category: str | None = None) -> PublishedNewsSnapshot:
    """Return at most ten polished entries from the newest published batch only."""
    selected_category = _selected_category(category)
    batch = session.scalar(
        select(PublicNewsBatch)
        .where(PublicNewsBatch.status == "published")
        .order_by(PublicNewsBatch.published_at.desc(), PublicNewsBatch.created_at.desc())
        .limit(1)
    )
    if batch is None:
        return PublishedNewsSnapshot(None, selected_category, (), {})

    counts = dict(
        session.execute(
            select(PublicNewsSelection.category, func.count())
            .where(PublicNewsSelection.batch_id == batch.id)
            .group_by(PublicNewsSelection.category)
        ).all()
    )
    rows = session.execute(
        select(PublicNewsSelection, NewsItem, NewsPolish)
        .join(NewsItem, NewsItem.id == PublicNewsSelection.news_item_id)
        .join(
            NewsPolish,
            (NewsPolish.news_item_id == NewsItem.id)
            & (NewsPolish.prompt_version == batch.prompt_version),
        )
        .where(
            PublicNewsSelection.batch_id == batch.id,
            PublicNewsSelection.category == selected_category,
        )
        .order_by(PublicNewsSelection.position)
        .limit(batch.target_count)
    ).all()
    items = tuple(
        PublicNewsDisplayItem(
            source=news.source,
            canonical_url=news.canonical_url,
            title=news.title,
            summary_zh=polish.content_zh,
            category=news.category,
            source_trust=news.source_trust,
            verification_status=news.verification_status,
        )
        for selection, news, polish in rows
        if polish.usage_json.get("status") in SUCCESSFUL_POLISH_STATUSES
        and selection.polish_status == "succeeded"
    )
    return PublishedNewsSnapshot(batch, selected_category, items, counts)
