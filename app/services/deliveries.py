"""Create a reproducible delivery job without sending it yet."""
from __future__ import annotations
import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import selectinload
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import DeliveryAttempt, DeliveryItem, DeliveryJob, Destination, NewsItem, Subscription
from app.services.destinations import decrypt_webhook
from app.services.polish import polish_for_delivery

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
    job = DeliveryJob(subscription_id=subscription.id, destination_id=destination_id, scheduled_for=scheduled_for, next_attempt_at=scheduled_for, idempotency_key=key)
    session.add(job); session.flush()
    for position, row in enumerate(selected, start=1):
        session.add(DeliveryItem(delivery_job_id=job.id, news_item_id=row.id, position=position))
    return job

def generate_due_jobs(session: Session, now: datetime) -> int:
    local_now = now.astimezone(ZoneInfo("Asia/Shanghai")).replace(second=0, microsecond=0)
    subscriptions = session.scalars(select(Subscription).where(Subscription.enabled.is_(True)).options(selectinload(Subscription.categories), selectinload(Subscription.schedules), selectinload(Subscription.destinations))).all()
    created = 0
    for subscription in subscriptions:
        due = any(schedule.enabled and schedule.local_time.hour == local_now.hour and schedule.local_time.minute == local_now.minute for schedule in subscription.schedules)
        if not due:
            continue
        for destination in subscription.destinations:
            if destination.verified_at and destination.credential_deleted_at is None and create_delivery_job(session, subscription, destination.id, now.replace(second=0, microsecond=0)):
                created += 1
    return created

RETRY_DELAYS = (1, 5, 15)

def claim_due_jobs(session: Session, now: datetime, limit: int = 20) -> list[DeliveryJob]:
    jobs = list(session.scalars(select(DeliveryJob).where(DeliveryJob.status.in_(("pending", "retrying")), DeliveryJob.next_attempt_at <= now).order_by(DeliveryJob.scheduled_for).with_for_update(skip_locked=True).limit(limit)))
    for job in jobs:
        job.status = "sending"; job.locked_at = now; job.attempts += 1
    session.flush()
    return jobs

def mark_sent(session: Session, job: DeliveryJob, now: datetime) -> None:
    job.status = "sent"; job.locked_at = None
    session.add(DeliveryAttempt(delivery_job_id=job.id, attempt_no=job.attempts, status="sent"))

def retry_or_fail(session: Session, job: DeliveryJob, now: datetime, error_code: str, retryable: bool = True) -> None:
    if not retryable or job.attempts >= len(RETRY_DELAYS):
        job.status = "failed"; job.locked_at = None
        status = "failed"
    else:
        job.status = "retrying"; job.locked_at = None; job.next_attempt_at = now + timedelta(minutes=RETRY_DELAYS[job.attempts - 1])
        status = "retrying"
    session.add(DeliveryAttempt(delivery_job_id=job.id, attempt_no=job.attempts, status=status, error_code=error_code[:64]))

def render_delivery(session: Session, job: DeliveryJob, api_key: str) -> str:
    rows = session.execute(select(DeliveryItem, NewsItem).join(NewsItem, NewsItem.id == DeliveryItem.news_item_id).where(DeliveryItem.delivery_job_id == job.id).order_by(DeliveryItem.position)).all()
    lines = ["Newsday 个性化新闻摘要"]
    for position, (_, news) in enumerate(rows, start=1):
        lines.append(f"{position}. {news.title}\n{polish_for_delivery(session, news, api_key)}\n原文：{news.canonical_url}")
    return "\n\n".join(lines)

def destination_webhook(session: Session, job: DeliveryJob, encryption_key: str) -> tuple[str, str]:
    destination = session.get(Destination, job.destination_id)
    return destination.kind, decrypt_webhook(destination.webhook_ciphertext, destination.webhook_nonce, encryption_key)
