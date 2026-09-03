"""Reusable ingestion worker that bridges existing sources into the web pool."""

from typing import Iterable

from sqlalchemy.orm import Session

from app.services.news import ingest_item
from finnews.sources.base import RawItem
from llm_polish import DEFAULT_PRIMARY_MODEL, DEFAULT_REPAIR_MODEL, polish_item


def ingest_batch(session: Session, items: Iterable[RawItem], api_key: str) -> int:
    """Polish each item once, then insert only unseen items into the public pool."""
    inserted = 0
    for item in items:
        result = polish_item(
            title=item.title,
            material=item.summary,
            source=item.source,
            api_key=api_key,
            primary_model=DEFAULT_PRIMARY_MODEL,
            repair_model=DEFAULT_REPAIR_MODEL,
        )
        if ingest_item(session, item, summary_zh=result.text):
            inserted += 1
    return inserted
