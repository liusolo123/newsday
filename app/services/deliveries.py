"""Create a reproducible delivery job without sending it yet."""
from __future__ import annotations
import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import DeliveryAttempt, DeliveryItem, DeliveryJob, Destination, NewsItem, Subscription, SubscriptionCategory
from app.services.destinations import decrypt_webhook
from app.services.news import trust_notice
from app.services.polish import polish_for_delivery

RETRY_DELAYS = (1, 5, 15)
SENDING_LOCK_TIMEOUT = timedelta(minutes=15)


class DeliveryCancelled(RuntimeError):
    """Raised when a claimed task is no longer eligible for external delivery."""


def _delivered_item_ids_for_local_day(
    session: Session, subscription_id: UUID, scheduled_for: datetime
) -> set[UUID]:
    local_time = scheduled_for.astimezone(ZoneInfo("Asia/Shanghai"))
    local_start = local_time.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    return set(
        session.scalars(
            select(DeliveryItem.news_item_id)
            .join(DeliveryJob, DeliveryJob.id == DeliveryItem.delivery_job_id)
            .where(
                DeliveryJob.subscription_id == subscription_id,
                DeliveryJob.status == "sent",
                DeliveryJob.scheduled_for >= local_start.astimezone(timezone.utc),
                DeliveryJob.scheduled_for < min(scheduled_for, local_end.astimezone(timezone.utc)),
            )
        )
    )


def create_delivery_job(session: Session, subscription: Subscription, destination_id: UUID, scheduled_for: datetime) -> DeliveryJob | None:
    existing = session.scalar(select(DeliveryJob).where(DeliveryJob.subscription_id == subscription.id, DeliveryJob.destination_id == destination_id, DeliveryJob.scheduled_for == scheduled_for))
    if existing:
        return None
    previous_item_ids = _delivered_item_ids_for_local_day(session, subscription.id, scheduled_for)
    selected = []
    seen = set()
    for choice in subscription.categories:
        rows = session.scalars(
            select(NewsItem)
            .where(NewsItem.category == choice.category)
            .order_by(NewsItem.score.desc(), NewsItem.published_at.desc())
        ).all()
        selected_for_category = 0
        for row in rows:
            if row.id not in previous_item_ids and row.url_hash not in seen:
                selected.append(row)
                seen.add(row.url_hash)
                selected_for_category += 1
                if selected_for_category == choice.item_limit:
                    break
    key = hashlib.sha256(f"{subscription.id}:{destination_id}:{scheduled_for.isoformat()}".encode()).hexdigest()
    job = DeliveryJob(subscription_id=subscription.id, destination_id=destination_id, scheduled_for=scheduled_for, next_attempt_at=scheduled_for, idempotency_key=key)
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        return None
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
            if destination.enabled and destination.verified_at and destination.credential_deleted_at is None and create_delivery_job(session, subscription, destination.id, now.replace(second=0, microsecond=0)):
                created += 1
    return created

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
    if not retryable or job.attempts > len(RETRY_DELAYS):
        job.status = "failed"; job.locked_at = None
        status = "failed"
    else:
        job.status = "retrying"; job.locked_at = None; job.next_attempt_at = now + timedelta(minutes=RETRY_DELAYS[job.attempts - 1])
        status = "retrying"
    session.add(DeliveryAttempt(delivery_job_id=job.id, attempt_no=job.attempts, status=status, error_code=error_code[:64]))


def recover_stale_sending_jobs(
    session: Session, now: datetime, lock_timeout: timedelta = SENDING_LOCK_TIMEOUT
) -> int:
    """Make abandoned claims retryable after a bounded lock timeout."""
    stale_jobs = list(
        session.scalars(
            select(DeliveryJob)
            .where(DeliveryJob.status == "sending", DeliveryJob.locked_at < now - lock_timeout)
            .with_for_update(skip_locked=True)
        )
    )
    for job in stale_jobs:
        job.locked_at = None
        if job.attempts > len(RETRY_DELAYS):
            job.status = "failed"
            status = "failed"
        else:
            job.status = "retrying"
            job.next_attempt_at = now
            status = "retrying"
        session.add(
            DeliveryAttempt(
                delivery_job_id=job.id,
                attempt_no=job.attempts,
                status=status,
                error_code="stale_sending_lock",
            )
        )
    session.flush()
    return len(stale_jobs)


def mark_cancelled(session: Session, job: DeliveryJob) -> None:
    job.status = "cancelled"
    job.locked_at = None
    session.add(
        DeliveryAttempt(
            delivery_job_id=job.id,
            attempt_no=job.attempts,
            status="cancelled",
            error_code="subscription_inactive",
        )
    )

def render_delivery(session: Session, job: DeliveryJob, api_key: str) -> str:
    rows = session.execute(select(DeliveryItem, NewsItem).join(NewsItem, NewsItem.id == DeliveryItem.news_item_id).where(DeliveryItem.delivery_job_id == job.id).order_by(DeliveryItem.position)).all()
    lines = ["Newsday 个性化新闻摘要"]
    requested_count = session.scalar(
        select(func.coalesce(func.sum(SubscriptionCategory.item_limit), 0))
        .join(Subscription, Subscription.id == SubscriptionCategory.subscription_id)
        .where(Subscription.id == job.subscription_id)
    )
    if len(rows) < requested_count:
        lines.append(f"本次新闻池仅有 {len(rows)} 条符合条件的未重复新闻，少于设定的 {requested_count} 条。")
    for position, (_, news) in enumerate(rows, start=1):
        notice = trust_notice(news)
        lines.append(
            f"{position}. {news.title}\n{polish_for_delivery(session, news, api_key)}"
            f"\n来源：{news.source}\n{notice + chr(10) if notice else ''}原文：{news.canonical_url}"
        )
    return "\n\n".join(lines)

def destination_webhook(session: Session, job: DeliveryJob, encryption_key: str) -> tuple[str, str]:
    destination = session.get(Destination, job.destination_id)
    subscription = session.get(Subscription, job.subscription_id)
    if (
        destination is None
        or subscription is None
        or not subscription.enabled
        or not destination.enabled
        or destination.verified_at is None
        or destination.credential_deleted_at is not None
    ):
        raise DeliveryCancelled("subscription_inactive")
    return destination.kind, decrypt_webhook(destination.webhook_ciphertext, destination.webhook_nonce, encryption_key)
