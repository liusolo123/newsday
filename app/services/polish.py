"""Chinese polishing shared by public news and subscription deliveries."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsItem, NewsPolish
from llm_polish import (
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_REPAIR_MODEL,
    PolishResult,
    polish_item,
)


PROMPT_VERSION = "summary-v2"
SUCCESSFUL_POLISH_STATUSES = frozenset(("flash", "pro"))


def _usage_payload(result) -> dict:
    attempts = [dict(usage) for usage in result.usage]
    totals = {
        key: sum(int(usage.get(key, 0)) for usage in attempts)
        for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens")
    }
    return {
        "status": result.status,
        "reason": result.reason[:120],
        "attempts": attempts,
        "totals": totals,
    }


def _is_successful_cache(cached: NewsPolish | None) -> bool:
    return bool(cached and cached.usage_json.get("status") in SUCCESSFUL_POLISH_STATUSES)


def polish_news(
    session: Session,
    news: NewsItem,
    api_key: str,
    *,
    prompt_version: str = PROMPT_VERSION,
) -> PolishResult:
    """Return a successful cached summary or retry a prior failed attempt."""
    cached = session.scalar(
        select(NewsPolish).where(
            NewsPolish.news_item_id == news.id,
            NewsPolish.prompt_version == prompt_version,
        )
    )
    if _is_successful_cache(cached):
        return PolishResult(cached.content_zh, str(cached.usage_json["status"]))
    result = polish_item(
        title=news.title,
        material=news.source_summary,
        source=news.source,
        api_key=api_key,
        primary_model=DEFAULT_PRIMARY_MODEL,
        repair_model=DEFAULT_REPAIR_MODEL,
    )
    model = str(result.usage[-1]["model"]) if result.usage else DEFAULT_PRIMARY_MODEL
    if cached is None:
        session.add(
            NewsPolish(
                news_item_id=news.id,
                model=model,
                prompt_version=prompt_version,
                content_zh=result.text,
                usage_json=_usage_payload(result),
            )
        )
    else:
        cached.model = model
        cached.content_zh = result.text
        cached.usage_json = _usage_payload(result)
    session.flush()
    return result


def polish_for_delivery(session: Session, news: NewsItem, api_key: str) -> str:
    return polish_news(session, news, api_key).text
