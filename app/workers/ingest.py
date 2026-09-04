"""Two-hour ingestion worker; AI polishing is intentionally deferred to delivery."""

from typing import Iterable, Mapping

from sqlalchemy.orm import Session

from app.services.news import ingest_item
from finnews.filter import score_items
from finnews.sources.base import RawItem
from finnews.pipeline import load_config
from finnews.sources import build_sources
from finnews.sources.base import make_session


def _item_identity(item: RawItem) -> tuple[str, str, str, str]:
    published_at = item.published_at.isoformat() if item.published_at else ""
    return item.source, item.title, item.url, published_at


def ingest_batch(
    session: Session, items: Iterable[RawItem], scores: Mapping[tuple[str, str, str, str], int] | None = None
) -> int:
    """Insert unseen raw items only; dispatch owns Chinese AI polishing."""
    inserted = 0
    for item in items:
        score = scores.get(_item_identity(item), 0) if scores else 0
        if ingest_item(session, item, score=score):
            inserted += 1
    return inserted

def fetch_and_ingest(session: Session, config_path: str) -> tuple[int, list[str]]:
    """Fetch configured sources once; callers decide the two-hour schedule."""
    config = load_config(config_path)
    http_session = make_session()
    failures: list[str] = []
    items: list[RawItem] = []
    source_weights: dict[str, int] = {}
    try:
        for source in build_sources(config, http_session):
            source_weights[source.name] = source.weight
            try:
                items.extend(source.fetch()[: int(config.get("max_per_source", 30))])
            except Exception as error:
                failures.append(f"{source.name}: {error}")
        scored = score_items(items, list(config.get("keywords") or []), source_weights)
        scores = {
            (item.source, item.title, item.url, item.published_at): item.score
            for item in scored
        }
        return ingest_batch(session, items, scores), failures
    finally:
        http_session.close()
