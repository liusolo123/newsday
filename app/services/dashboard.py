"""Read-only dashboard summary and pause/resume control."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.models import DeliveryJob, Subscription

def dashboard_summary(session: Session, user_id):
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == user_id).options(selectinload(Subscription.schedules)))
    jobs = [] if subscription is None else list(session.scalars(select(DeliveryJob).where(DeliveryJob.subscription_id == subscription.id, DeliveryJob.scheduled_for >= datetime.now(timezone.utc) - timedelta(days=7)).order_by(DeliveryJob.scheduled_for.desc()).limit(20)))
    next_time = None
    if subscription and subscription.enabled and subscription.schedules:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        candidates = []
        for schedule in subscription.schedules:
            candidate = now.replace(hour=schedule.local_time.hour, minute=schedule.local_time.minute, second=0, microsecond=0)
            if candidate <= now: candidate += timedelta(days=1)
            candidates.append(candidate)
        next_time = min(candidates).strftime("%m-%d %H:%M")
    return subscription, next_time, jobs

def set_subscription_enabled(session: Session, user_id, enabled: bool) -> bool:
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if subscription is None: return False
    subscription.enabled = enabled
    return True
