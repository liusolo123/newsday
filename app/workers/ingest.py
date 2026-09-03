"""Two-hour ingestion worker; AI polishing is intentionally deferred to delivery."""

from typing import Iterable

from sqlalchemy.orm import Session

from app.services.news import ingest_item
from finnews.sources.base import RawItem
from finnews.pipeline import load_config
from finnews.sources import build_sources
from finnews.sources.base import make_session


def ingest_batch(session: Session, items: Iterable[RawItem]) -> int:
    """Insert unseen raw items only; dispatch owns Chinese AI polishing."""
    inserted = 0
    for item in items:
        if ingest_item(session, item):
            inserted += 1
    return inserted

def fetch_and_ingest(session: Session, config_path: str) -> tuple[int, list[str]]:
    """Fetch configured sources once; callers decide the two-hour schedule."""
    config = load_config(config_path)
    http_session = make_session()
    failures: list[str] = []
    items: list[RawItem] = []
    for source in build_sources(config, http_session):
        try:
            items.extend(source.fetch()[: int(config.get("max_per_source", 30))])
        except Exception as error:
            failures.append(f"{source.name}: {error}")
    return ingest_batch(session, items), failures
