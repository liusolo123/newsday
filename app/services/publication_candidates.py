"""Build quality-gated candidates for a future public-news display batch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsItem
from app.models.subscription import CATEGORY_VALUES
from app.services.news import public_source_url


PUBLIC_NEWS_LIMIT = 10
CANDIDATE_WINDOWS_HOURS = (24, 72, 24 * 7)

# These are bounded, existing adapters that a later worker can use when a
# category remains short after searching the retained pool. They are advisory
# metadata here; candidate selection itself never performs network I/O.
CATEGORY_BACKFILL_SOURCES = {
    "ai": ("google_ai", "jiqizhixin_rss", "venturebeat_rss"),
    "technology": ("google_technology", "oschina_rss", "arstechnica_rss"),
    "consumer_electronics": ("google_consumer_electronics", "theverge_rss"),
    "github": ("github_blog", "github_trending", "github_search"),
    "business": ("google_business",),
    "markets": ("google_markets", "eastmoney_724", "wallstreetcn"),
    "politics": ("google_politics",),
    "sports": ("google_sports",),
    "entertainment": ("google_entertainment",),
    "social_trends": ("google_social_trends", "weibo_hot"),
}


@dataclass(frozen=True)
class CategoryCandidateResult:
    """Ranked, valid candidates and an explicit shortage record for one category."""

    category: str
    items: tuple[NewsItem, ...]
    target_count: int
    searched_hours: int
    deficit: dict[str, object] | None


def _tier_bounds(now: datetime, hours: int, previous_hours: int | None) -> tuple[datetime, datetime | None]:
    lower = now - timedelta(hours=hours)
    upper = now - timedelta(hours=previous_hours) if previous_hours is not None else None
    return lower, upper


def _eligible(item: NewsItem) -> bool:
    return bool(public_source_url(item.source, item.canonical_url))


def select_category_candidates(
    session: Session,
    category: str,
    *,
    now: datetime,
    target_count: int = PUBLIC_NEWS_LIMIT,
) -> CategoryCandidateResult:
    """Select up to ten valid, unique news items without crossing categories.

    Fresh news is preferred by filling the 24-hour tier before looking at the
    72-hour and seven-day tiers. Within each tier, score and publication time
    retain the existing project ranking semantics.
    """
    if category not in CATEGORY_VALUES:
        raise ValueError(f"Unsupported category: {category}")
    if not 1 <= target_count <= PUBLIC_NEWS_LIMIT:
        raise ValueError(f"target_count must be between 1 and {PUBLIC_NEWS_LIMIT}")

    selected: list[NewsItem] = []
    seen_url_hashes: set[str] = set()
    previous_hours: int | None = None
    for hours in CANDIDATE_WINDOWS_HOURS:
        lower, upper = _tier_bounds(now, hours, previous_hours)
        query = (
            select(NewsItem)
            .where(NewsItem.category == category, NewsItem.published_at >= lower)
            .order_by(NewsItem.score.desc(), NewsItem.published_at.desc())
        )
        if upper is not None:
            query = query.where(NewsItem.published_at < upper)
        for item in session.scalars(query):
            if item.url_hash in seen_url_hashes or not _eligible(item):
                continue
            selected.append(item)
            seen_url_hashes.add(item.url_hash)
            if len(selected) == target_count:
                return CategoryCandidateResult(category, tuple(selected), target_count, hours, None)
        previous_hours = hours

    deficit = {
        "target": target_count,
        "actual": len(selected),
        "reason": "insufficient_eligible_candidates",
        "searched_hours": CANDIDATE_WINDOWS_HOURS[-1],
        "backfill_sources": list(CATEGORY_BACKFILL_SOURCES[category]),
    }
    return CategoryCandidateResult(
        category,
        tuple(selected),
        target_count,
        CANDIDATE_WINDOWS_HOURS[-1],
        deficit,
    )


def select_all_category_candidates(
    session: Session,
    categories: Iterable[str] = CATEGORY_VALUES,
    *,
    now: datetime,
    target_count: int = PUBLIC_NEWS_LIMIT,
) -> dict[str, CategoryCandidateResult]:
    """Build independent candidate lists so shortages remain isolated by category."""
    return {
        category: select_category_candidates(
            session, category, now=now, target_count=target_count
        )
        for category in categories
    }
