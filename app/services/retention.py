"""Bounded seven-day cleanup that keeps delivery audit metadata."""
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.models import DeliveryItem, NewsItem, NewsPolish

def cleanup_expired_news(session: Session, now: Optional[datetime] = None, retention_days: int = 7, apply: bool = False) -> dict[str, int]:
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    ids = list(session.scalars(select(NewsItem.id).where(NewsItem.published_at < cutoff)))
    if not apply or not ids:
        return {"news_items": len(ids), "news_polishes": 0, "delivery_items": 0}
    polishes = session.execute(delete(NewsPolish).where(NewsPolish.news_item_id.in_(ids))).rowcount or 0
    items = session.execute(delete(DeliveryItem).where(DeliveryItem.news_item_id.in_(ids))).rowcount or 0
    news = session.execute(delete(NewsItem).where(NewsItem.id.in_(ids))).rowcount or 0
    return {"news_items": news, "news_polishes": polishes, "delivery_items": items}
