"""Bounded content cleanup that keeps delivery and audit metadata."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.models import DeliveryItem, NewsItem, NewsPolish
from cleanup import find_expired, remove_artifacts

def cleanup_expired_news(session: Session, now: Optional[datetime] = None, retention_days: int = 7, apply: bool = False, root: Path | None = None, batch_size: int = 200) -> dict[str, int]:
    if retention_days < 1 or batch_size < 1:
        raise ValueError("retention_days must be positive")
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    ids = list(session.scalars(select(NewsItem.id).where(NewsItem.published_at < cutoff)))
    artifacts = []
    if root is not None:
        _, artifacts = find_expired(root, retention_days=retention_days, today=cutoff.date() + timedelta(days=retention_days))
    result = {
        "news_items": len(ids),
        "news_polishes": 0,
        "delivery_items": 0,
        "legacy_artifacts": len(artifacts),
        "legacy_bytes": sum(artifact.size for artifact in artifacts),
    }
    if not apply or not ids:
        if apply and artifacts:
            result["legacy_artifacts"], result["legacy_bytes"] = remove_artifacts(artifacts)
        return result
    polishes = items = news = 0
    for offset in range(0, len(ids), batch_size):
        batch = ids[offset : offset + batch_size]
        polishes += session.execute(delete(NewsPolish).where(NewsPolish.news_item_id.in_(batch))).rowcount or 0
        items += session.execute(delete(DeliveryItem).where(DeliveryItem.news_item_id.in_(batch))).rowcount or 0
        news += session.execute(delete(NewsItem).where(NewsItem.id.in_(batch))).rowcount or 0
    result.update(news_items=news, news_polishes=polishes, delivery_items=items)
    if artifacts:
        result["legacy_artifacts"], result["legacy_bytes"] = remove_artifacts(artifacts)
    return result
