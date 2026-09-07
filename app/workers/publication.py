"""Background entrypoint for freezing and polishing the next public-news batch."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import PublicNewsBatch
from app.services.publication_snapshots import freeze_public_news_batch
from app.services.publication_workflow import process_public_news_batch


def prepare_public_news_batch(session: Session, api_key: str) -> PublicNewsBatch:
    """Durably freeze a new batch, then polish it before any later publication step."""
    batch = freeze_public_news_batch(session, now=datetime.now(timezone.utc))
    # Save the immutable selection before calling an external model service.
    session.commit()
    result = process_public_news_batch(session, batch.id, api_key)
    session.commit()
    return result
