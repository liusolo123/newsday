"""Audit and apply only deterministic historical source-link repairs."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsItem
from app.services.news import public_source_url


@dataclass(frozen=True)
class SourceLinkRepairPlan:
    """A reviewable repair plan; it never performs network guesses."""

    repairs: tuple[tuple[NewsItem, str], ...]
    invalid_unrepairable: int
    unchanged: int


def plan_source_link_repairs(session: Session) -> SourceLinkRepairPlan:
    """Plan deterministic repairs and count records that intentionally remain untouched.

    At present only the historical WallstreetCN ``/live/<id>`` route has a
    lossless replacement.  Generic Eastmoney and Sina channel URLs are
    reported as unrepairable: resolving them would require guessing an article
    from external APIs and must not silently alter historical records.
    """
    repairs: list[tuple[NewsItem, str]] = []
    invalid_unrepairable = 0
    unchanged = 0
    for item in session.scalars(select(NewsItem).order_by(NewsItem.id)):
        repaired_url = public_source_url(item.source, item.canonical_url)
        if item.source == "wallstreetcn" and repaired_url and repaired_url != item.canonical_url:
            repairs.append((item, repaired_url))
        elif not repaired_url:
            invalid_unrepairable += 1
        else:
            unchanged += 1
    return SourceLinkRepairPlan(tuple(repairs), invalid_unrepairable, unchanged)


def apply_source_link_repairs(session: Session, plan: SourceLinkRepairPlan) -> int:
    """Apply a previously reviewed deterministic plan in the caller's transaction."""
    for item, repaired_url in plan.repairs:
        item.canonical_url = repaired_url
    session.flush()
    return len(plan.repairs)
