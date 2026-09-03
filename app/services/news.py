"""Ingest existing normalized source items into the public news pool."""

import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from finnews.sources.base import RawItem
from finnews.storage import url_key
from llm_polish import chinese_fallback

from app.models import NewsItem
from app.models.subscription import CATEGORY_VALUES


CATEGORY_RULES = {
    "ai": ("ai", "人工智能", "大模型", "agent", "模型", "openai"), "github": ("github", "开源", "repo"),
    "consumer_electronics": ("手机", "电脑", "iphone", "ipad", "wearable"), "markets": ("股", "基金", "债券", "汇率", "加密", "bitcoin"),
    "business": ("经济", "公司", "财报", "贸易", "宏观", "cpi"), "politics": ("政策", "外交", "政府", "选举"),
    "sports": ("比赛", "联赛", "足球", "篮球", "奥运"), "entertainment": ("电影", "音乐", "综艺", "游戏", "艺人"),
    "social_trends": ("热搜", "微博"),
}


def classify_news(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    for category, keywords in CATEGORY_RULES.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "technology"


def ingest_item(session: Session, item: RawItem, score: int = 0, summary_zh: str = "") -> Optional[NewsItem]:
    canonical_url = url_key(item.url, item.title)
    digest = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    if session.scalar(select(NewsItem.id).where(NewsItem.url_hash == digest)):
        return None
    category = classify_news(item.title, item.summary)
    if category not in CATEGORY_VALUES:
        category = "technology"
    news = NewsItem(source=item.source, canonical_url=item.url or canonical_url, url_hash=digest, title=item.title.strip(), summary_zh=summary_zh.strip() or chinese_fallback(), category=category, tags=[], score=score, published_at=item.published_at or datetime.now(timezone.utc))
    session.add(news)
    session.flush()
    return news


def public_news(session: Session, category: Optional[str] = None, limit: int = 30) -> list[NewsItem]:
    query = select(NewsItem).order_by(NewsItem.published_at.desc(), NewsItem.score.desc()).limit(limit)
    if category in CATEGORY_VALUES:
        query = query.where(NewsItem.category == category)
    return list(session.scalars(query))
