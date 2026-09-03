"""Delivery-time Chinese polishing with a per-news-item cache."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsItem, NewsPolish
from llm_polish import DEFAULT_PRIMARY_MODEL, DEFAULT_REPAIR_MODEL, polish_item


PROMPT_VERSION = "delivery-v1"


def polish_for_delivery(session: Session, news: NewsItem, api_key: str) -> str:
    cached = session.scalar(select(NewsPolish).where(NewsPolish.news_item_id == news.id, NewsPolish.prompt_version == PROMPT_VERSION))
    if cached:
        return cached.content_zh
    result = polish_item(title=news.title, material=news.source_summary, source=news.source, api_key=api_key, primary_model=DEFAULT_PRIMARY_MODEL, repair_model=DEFAULT_REPAIR_MODEL)
    session.add(NewsPolish(news_item_id=news.id, model=DEFAULT_PRIMARY_MODEL, prompt_version=PROMPT_VERSION, content_zh=result.text, usage_json={"status": result.status}))
    return result.text
