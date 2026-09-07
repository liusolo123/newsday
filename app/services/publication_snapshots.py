"""Freeze category candidates into one auditable public-news batch."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import NewsItem, PublicNewsBatch, PublicNewsSelection
from app.models.subscription import CATEGORY_VALUES
from app.services.publication_candidates import (
    PUBLIC_NEWS_LIMIT,
    CategoryCandidateResult,
    select_all_category_candidates,
)


ALL_CATEGORY_PER_SOURCE_CAP = 3


@dataclass(frozen=True)
class AllCandidate:
    """A selected all-feed candidate with the phase that admitted it."""

    category: str
    item: NewsItem
    phase: str


def _item_sort_key(item: NewsItem) -> tuple[int, float, str]:
    return (-item.score, -item.published_at.timestamp(), str(item.id))


def _all_candidates(
    category_results: dict[str, CategoryCandidateResult], target_count: int
) -> tuple[AllCandidate, ...]:
    """Mix frozen category lists without letting one category dominate the all feed."""
    entries = [
        (category, item)
        for category, result in category_results.items()
        for item in result.items
    ]
    entries.sort(key=lambda entry: _item_sort_key(entry[1]))

    selected: list[AllCandidate] = []
    selected_ids: set[object] = set()
    category_counts: Counter[str] = Counter()

    # First give every populated category one slot, favouring the strongest
    # representative when there are more categories than available slots.
    representatives: dict[str, NewsItem] = {}
    for category, item in entries:
        representatives.setdefault(category, item)
    for category, item in sorted(representatives.items(), key=lambda entry: _item_sort_key(entry[1])):
        if len(selected) == target_count:
            return tuple(selected)
        selected.append(AllCandidate(category, item, "category_coverage"))
        selected_ids.add(item.id)
        category_counts[category] += 1

    # Fill on quality while retaining the normal three-per-category cap.
    for category, item in entries:
        if len(selected) == target_count:
            return tuple(selected)
        if item.id in selected_ids or category_counts[category] >= ALL_CATEGORY_PER_SOURCE_CAP:
            continue
        selected.append(AllCandidate(category, item, "capped_quality"))
        selected_ids.add(item.id)
        category_counts[category] += 1

    # A small number of healthy categories must not leave the page needlessly
    # short, so use the remaining already-frozen items after the cap is met.
    for category, item in entries:
        if len(selected) == target_count:
            break
        if item.id in selected_ids:
            continue
        selected.append(AllCandidate(category, item, "quality_overflow"))
        selected_ids.add(item.id)

    return tuple(selected)


def _category_selection_reason(result: CategoryCandidateResult, item: NewsItem) -> dict[str, object]:
    return {
        "policy": "category-v1",
        "searched_hours": result.searched_hours,
        "score": item.score,
        "source": item.source,
    }


def freeze_public_news_batch(
    session: Session,
    *,
    now: datetime,
    categories: Iterable[str] = CATEGORY_VALUES,
    target_count: int = PUBLIC_NEWS_LIMIT,
    prompt_version: str = "summary-v2",
) -> PublicNewsBatch:
    """Persist a complete selection snapshot, ready for the later polish worker.

    The caller owns the enclosing transaction: a failure before commit cannot
    expose a partial batch. No model request and no public-page switch happen
    in this function.
    """
    if not 1 <= target_count <= PUBLIC_NEWS_LIMIT:
        raise ValueError(f"target_count must be between 1 and {PUBLIC_NEWS_LIMIT}")
    category_list = tuple(categories)
    if len(set(category_list)) != len(category_list):
        raise ValueError("categories must not contain duplicates")
    if any(category not in CATEGORY_VALUES for category in category_list):
        raise ValueError("categories contain an unsupported value")

    category_results = select_all_category_candidates(
        session, category_list, now=now, target_count=target_count
    )
    deficits = {
        category: result.deficit
        for category, result in category_results.items()
        if result.deficit is not None
    }
    all_items = _all_candidates(category_results, target_count)
    if len(all_items) < target_count:
        deficits["all"] = {
            "target": target_count,
            "actual": len(all_items),
            "reason": "insufficient_frozen_candidates",
            "covered_categories": sorted({candidate.category for candidate in all_items}),
        }

    batch = PublicNewsBatch(
        status="polishing",
        selection_policy_version="public-v1",
        prompt_version=prompt_version,
        target_count=target_count,
        deficits=deficits,
    )
    session.add(batch)
    session.flush()

    for category, result in category_results.items():
        for position, item in enumerate(result.items, start=1):
            session.add(
                PublicNewsSelection(
                    batch_id=batch.id,
                    news_item_id=item.id,
                    category=category,
                    position=position,
                    selection_reason=_category_selection_reason(result, item),
                )
            )
    for position, candidate in enumerate(all_items, start=1):
        session.add(
            PublicNewsSelection(
                batch_id=batch.id,
                news_item_id=candidate.item.id,
                category="all",
                position=position,
                selection_reason={
                    "policy": "all-v1",
                    "phase": candidate.phase,
                    "source_category": candidate.category,
                    "score": candidate.item.score,
                },
            )
        )
    session.flush()
    return batch
