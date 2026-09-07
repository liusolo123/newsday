"""Polish frozen public-news batches without exposing incomplete content."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsItem, PublicNewsBatch, PublicNewsSelection
from app.services.polish import SUCCESSFUL_POLISH_STATUSES, polish_news


def process_public_news_batch(
    session: Session, batch_id: UUID, api_key: str
) -> PublicNewsBatch:
    """Process each unique frozen item once and mark the batch ready only on success.

    No commit is issued here. The worker commits the frozen snapshot before
    model requests, and commits this result afterwards, so callers never expose
    a partially polished batch to the public page.
    """
    batch = session.get(PublicNewsBatch, batch_id)
    if batch is None:
        raise ValueError("public news batch does not exist")
    if batch.status not in {"polishing", "failed"}:
        raise ValueError(f"batch is not eligible for polishing: {batch.status}")

    selections = list(
        session.scalars(
            select(PublicNewsSelection).where(PublicNewsSelection.batch_id == batch.id)
        )
    )
    if not selections:
        batch.status = "failed"
        session.flush()
        return batch

    selections_by_item: dict[UUID, list[PublicNewsSelection]] = defaultdict(list)
    for selection in selections:
        selections_by_item[selection.news_item_id].append(selection)

    batch.status = "polishing"
    for news_item_id, item_selections in selections_by_item.items():
        news = session.get(NewsItem, news_item_id)
        try:
            result = polish_news(session, news, api_key, prompt_version=batch.prompt_version)
            status = "succeeded" if result.status in SUCCESSFUL_POLISH_STATUSES else "failed"
        except Exception as error:  # Keep other selected news eligible for processing.
            status = "failed"
            for selection in item_selections:
                selection.selection_reason = {
                    **(selection.selection_reason or {}),
                    "polish_error": type(error).__name__[:64],
                }
        for selection in item_selections:
            selection.polish_status = status

    batch.status = "ready" if all(selection.polish_status == "succeeded" for selection in selections) else "failed"
    session.flush()
    return batch
