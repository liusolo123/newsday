"""Safe, administrator-only operational summaries and subscription controls."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import DeliveryAttempt, DeliveryJob, Destination, Subscription, User
from app.services.dashboard import set_subscription_enabled


def admin_subscription_rows(session: Session) -> list[dict[str, object]]:
    """Return display-only subscription data; never expose credentials or webhooks."""
    users = session.scalars(
        select(User)
        .options(
            selectinload(User.subscription).selectinload(Subscription.destinations),
            selectinload(User.subscription).selectinload(Subscription.schedules),
        )
        .order_by(User.created_at.desc())
    ).all()
    return [
        {
            "user_id": str(user.id),
            "username": user.username,
            "account_status": user.status,
            "has_subscription": user.subscription is not None,
            "subscription_enabled": user.subscription.enabled if user.subscription else False,
            "destination_count": len(user.subscription.destinations) if user.subscription else 0,
            "verified_destination_count": sum(
                destination.verified_at is not None for destination in user.subscription.destinations
            ) if user.subscription else 0,
            "schedule_count": len(user.subscription.schedules) if user.subscription else 0,
        }
        for user in users
    ]


def admin_recent_deliveries(session: Session, limit: int = 20) -> list[dict[str, object]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    rows = session.execute(
        select(DeliveryJob, User.username)
        .join(Subscription, DeliveryJob.subscription_id == Subscription.id)
        .join(User, Subscription.user_id == User.id)
        .where(DeliveryJob.scheduled_for >= cutoff)
        .order_by(DeliveryJob.scheduled_for.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": str(job.id),
            "destination_id": str(job.destination_id),
            "username": username,
            "status": job.status,
            "attempts": job.attempts,
            "scheduled_for": job.scheduled_for,
        }
        for job, username in rows
    ]


def admin_failed_deliveries(session: Session, limit: int = 50) -> list[dict[str, object]]:
    rows = session.execute(
        select(DeliveryJob, User.username)
        .join(Subscription, DeliveryJob.subscription_id == Subscription.id)
        .join(User, Subscription.user_id == User.id)
        .where(DeliveryJob.status == "failed")
        .order_by(DeliveryJob.scheduled_for.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": str(job.id),
            "destination_id": str(job.destination_id),
            "username": username,
            "attempts": job.attempts,
            "scheduled_for": job.scheduled_for,
        }
        for job, username in rows
    ]


def retry_failed_delivery(session: Session, job_id: UUID) -> bool:
    job = session.get(DeliveryJob, job_id)
    if job is None or job.status != "failed":
        return False
    job.status = "retrying"
    job.locked_at = None
    job.next_attempt_at = datetime.now(timezone.utc)
    session.add(
        DeliveryAttempt(
            delivery_job_id=job.id,
            attempt_no=job.attempts,
            status="retrying",
            error_code="admin_retry",
        )
    )
    session.flush()
    return True


def set_destination_enabled(session: Session, destination_id: UUID, enabled: bool) -> bool:
    destination = session.get(Destination, destination_id)
    if destination is None:
        return False
    destination.enabled = enabled
    session.flush()
    return True


def set_admin_subscription_enabled(session: Session, user_id: UUID, enabled: bool) -> bool:
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if subscription is None:
        return False
    return set_subscription_enabled(session, user_id, enabled)
