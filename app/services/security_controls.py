"""Database-backed abuse controls and safe administrator audit trails."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, RateLimitEvent, User


class RateLimitError(ValueError):
    """Raised before a sensitive action exceeds its permitted attempt rate."""


def _identifier_hash(identifier: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), identifier.encode("utf-8"), hashlib.sha256).hexdigest()


def enforce_rate_limit(
    session: Session,
    action: str,
    identifier: str,
    secret: str,
    maximum: int,
    window_minutes: int = 15,
    now: datetime | None = None,
) -> None:
    """Record an attempt unless the rolling window is already full."""
    now = now or datetime.now(timezone.utc)
    identifier_hash = _identifier_hash(identifier, secret)
    cutoff = now - timedelta(minutes=window_minutes)
    attempts = session.scalar(
        select(func.count(RateLimitEvent.id)).where(
            RateLimitEvent.action == action,
            RateLimitEvent.identifier_hash == identifier_hash,
            RateLimitEvent.created_at >= cutoff,
        )
    )
    if attempts >= maximum:
        raise RateLimitError("请求过于频繁，请稍后再试")
    session.add(RateLimitEvent(action=action, identifier_hash=identifier_hash, created_at=now))
    session.flush()


def record_audit_event(
    session: Session, actor_user_id: UUID, action: str, target_type: str, target_id: UUID | str
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
        )
    )


def recent_audit_events(session: Session, limit: int = 20) -> list[dict[str, object]]:
    rows = session.execute(
        select(AuditEvent, User.username)
        .outerjoin(User, AuditEvent.actor_user_id == User.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "actor": username or "system",
            "action": event.action,
            "target_type": event.target_type,
            "created_at": event.created_at,
        }
        for event, username in rows
    ]
