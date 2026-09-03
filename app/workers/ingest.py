"""Two-hour ingestion worker; AI polishing is intentionally deferred to delivery."""

from typing import Iterable

from sqlalchemy.orm import Session

from app.services.news import ingest_item
from finnews.sources.base import RawItem


def ingest_batch(session: Session, items: Iterable[RawItem]) -> int:
    """Insert unseen raw items only; dispatch owns Chinese AI polishing."""
    inserted = 0
    for item in items:
        if ingest_item(session, item):
            inserted += 1
    return inserted
