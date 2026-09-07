"""Background entrypoint for freezing and polishing the next public-news batch."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PublicNewsBatch
from app.services.publication_snapshots import freeze_public_news_batch
from app.services.publication_workflow import process_public_news_batch


def prepare_public_news_batch(session: Session, api_key: str) -> PublicNewsBatch:
    """Resume an unfinished batch or durably freeze and polish a new one."""
    batch = session.scalar(
        select(PublicNewsBatch)
        .where(PublicNewsBatch.status.in_(("polishing", "failed")))
        .order_by(PublicNewsBatch.created_at.desc())
        .limit(1)
    )
    if batch is None:
        batch = freeze_public_news_batch(session, now=datetime.now(timezone.utc))
        # Save the immutable selection before calling an external model service.
        session.commit()
    result = process_public_news_batch(session, batch.id, api_key)
    session.commit()
    return result
