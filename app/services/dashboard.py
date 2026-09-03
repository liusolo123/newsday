"""Read-only dashboard summary and subscription lifecycle controls."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload
from app.models import DeliveryJob, Subscription
from app.services.destinations import remove_destination_credentials

def dashboard_summary(session: Session, user_id):
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == user_id).options(selectinload(Subscription.categories), selectinload(Subscription.schedules), selectinload(Subscription.destinations)))
    jobs = [] if subscription is None else list(session.scalars(select(DeliveryJob).where(DeliveryJob.subscription_id == subscription.id, DeliveryJob.scheduled_for >= datetime.now(timezone.utc) - timedelta(days=7)).order_by(DeliveryJob.scheduled_for.desc()).limit(20)))
    next_time = None
    delivery_ready = bool(subscription and subscription.enabled and any(destination.verified_at and destination.credential_deleted_at is None for destination in subscription.destinations))
    if delivery_ready and subscription and subscription.schedules:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        candidates = []
        for schedule in subscription.schedules:
            candidate = now.replace(hour=schedule.local_time.hour, minute=schedule.local_time.minute, second=0, microsecond=0)
            if candidate <= now: candidate += timedelta(days=1)
            candidates.append(candidate)
        next_time = min(candidates).strftime("%m-%d %H:%M")
    return subscription, next_time, jobs

def set_subscription_enabled(session: Session, user_id, enabled: bool, *, now: datetime | None = None) -> bool:
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if subscription is None: return False
    subscription.enabled = enabled
    if not enabled:
        session.execute(
            update(DeliveryJob)
            .where(
                DeliveryJob.subscription_id == subscription.id,
                DeliveryJob.scheduled_for >= (now or datetime.now(timezone.utc)),
                DeliveryJob.status.in_(("pending", "retrying")),
            )
            .values(status="cancelled", locked_at=None)
        )
    session.flush()
    return True


def cancel_subscription(session: Session, user_id, *, delete_credentials: bool) -> bool:
    """Cancel future work without deleting delivery audit rows."""
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if subscription is None:
        return False
    subscription.enabled = False
    session.execute(
        update(DeliveryJob)
        .where(
            DeliveryJob.subscription_id == subscription.id,
            DeliveryJob.status.in_(("pending", "retrying")),
        )
        .values(status="cancelled", locked_at=None)
    )
    if delete_credentials:
        remove_destination_credentials(session, user_id)
    session.flush()
    return True
