"""Create a reproducible delivery job without sending it yet."""
import hashlib
from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import DeliveryItem, DeliveryJob, NewsItem, Subscription

def create_delivery_job(session: Session, subscription: Subscription, destination_id: UUID, scheduled_for: datetime) -> DeliveryJob | None:
    existing = session.scalar(select(DeliveryJob).where(DeliveryJob.subscription_id == subscription.id, DeliveryJob.destination_id == destination_id, DeliveryJob.scheduled_for == scheduled_for))
    if existing:
        return None
    selected = []
    seen = set()
    for choice in subscription.categories:
        rows = session.scalars(select(NewsItem).where(NewsItem.category == choice.category).order_by(NewsItem.score.desc(), NewsItem.published_at.desc()).limit(choice.item_limit)).all()
        for row in rows:
            if row.url_hash not in seen:
                selected.append(row); seen.add(row.url_hash)
    key = hashlib.sha256(f"{subscription.id}:{destination_id}:{scheduled_for.isoformat()}".encode()).hexdigest()
    job = DeliveryJob(subscription_id=subscription.id, destination_id=destination_id, scheduled_for=scheduled_for, idempotency_key=key)
    session.add(job); session.flush()
    for position, row in enumerate(selected, start=1):
        session.add(DeliveryItem(delivery_job_id=job.id, news_item_id=row.id, position=position))
    return job
