"""Validated persistence for a user's single Newsday subscription."""

from datetime import time
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Schedule, Subscription, SubscriptionCategory
from app.models.subscription import CATEGORY_VALUES


class SubscriptionValidationError(ValueError):
    """Raised when a subscription cannot be safely saved."""


def parse_local_times(values: Iterable[str]) -> list[time]:
    parsed: list[time] = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        try:
            parsed.append(time.fromisoformat(value))
        except ValueError as error:
            raise SubscriptionValidationError("发送时间格式无效") from error
    if not 1 <= len(parsed) <= 3 or len(set(parsed)) != len(parsed):
        raise SubscriptionValidationError("每天需要设置 1–3 个不重复的发送时间")
    return sorted(parsed)


def validate_categories(selections: dict[str, int]) -> dict[str, int]:
    if not selections:
        raise SubscriptionValidationError("请至少选择一个新闻主题")
    if len(selections) > len(CATEGORY_VALUES):
        raise SubscriptionValidationError("主题选择无效")
    if any(category not in CATEGORY_VALUES for category in selections):
        raise SubscriptionValidationError("主题选择无效")
    if any(limit < 5 or limit > 10 for limit in selections.values()):
        raise SubscriptionValidationError("每个主题需要选择 5–10 条新闻")
    if sum(selections.values()) > 50:
        raise SubscriptionValidationError("单次投递最多包含 50 条新闻")
    return selections


def save_subscription(
    session: Session, user_id: UUID, selections: dict[str, int], local_times: Iterable[str]
) -> Subscription:
    selections = validate_categories(selections)
    times = parse_local_times(local_times)
    subscription = session.scalar(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .options(selectinload(Subscription.categories), selectinload(Subscription.schedules))
    )
    if subscription is None:
        subscription = Subscription(user_id=user_id)
        session.add(subscription)
        session.flush()
    subscription.enabled = True
    subscription.timezone = "Asia/Shanghai"
    subscription.categories.clear()
    subscription.schedules.clear()
    subscription.categories.extend(
        SubscriptionCategory(category=category, item_limit=limit)
        for category, limit in sorted(selections.items())
    )
    subscription.schedules.extend(Schedule(local_time=value) for value in times)
    session.flush()
    return subscription


def load_subscription(session: Session, user_id: UUID) -> Optional[Subscription]:
    return session.scalar(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .options(selectinload(Subscription.categories), selectinload(Subscription.schedules))
    )
