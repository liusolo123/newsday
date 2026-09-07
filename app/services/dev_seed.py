"""Deterministic, development-only public news records for local UI work."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsItem, NewsPolish, PublicNewsBatch, PublicNewsSelection
from app.models.subscription import CATEGORY_VALUES
from app.services.polish import PROMPT_VERSION


SEED_POLICY_VERSION = "dev-seed-v1"
SEED_ITEMS_PER_CATEGORY = 10

_CATEGORY_LABELS = {
    "ai": "AI",
    "technology": "科技",
    "consumer_electronics": "消费电子",
    "github": "GitHub",
    "business": "财经",
    "markets": "投资市场",
    "politics": "时政",
    "sports": "体育",
    "entertainment": "娱乐",
    "social_trends": "社会热搜",
}


def seed_development_public_news(
    session: Session, *, now: datetime | None = None
) -> PublicNewsBatch:
    """Create one complete local snapshot without models, feeds, or network access."""
    existing = session.scalar(
        select(PublicNewsBatch)
        .where(
            PublicNewsBatch.selection_policy_version == SEED_POLICY_VERSION,
            PublicNewsBatch.status == "published",
        )
        .order_by(PublicNewsBatch.published_at.desc(), PublicNewsBatch.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing

    published_at = now or datetime.now(timezone.utc)
    batch = PublicNewsBatch(
        status="published",
        selection_policy_version=SEED_POLICY_VERSION,
        prompt_version=PROMPT_VERSION,
        target_count=SEED_ITEMS_PER_CATEGORY,
        deficits={},
        published_at=published_at,
    )
    session.add(batch)
    session.flush()

    all_items: list[NewsItem] = []
    for category_index, category in enumerate(CATEGORY_VALUES):
        label = _CATEGORY_LABELS[category]
        for position in range(1, SEED_ITEMS_PER_CATEGORY + 1):
            canonical_url = f"https://example.com/news/{category}/{position}"
            news = NewsItem(
                source="local-demo",
                canonical_url=canonical_url,
                url_hash=sha256(canonical_url.encode("utf-8")).hexdigest(),
                title=f"本地演示｜{label}新闻第 {position} 条",
                source_summary=f"用于本地展示 {label} 分类第 {position} 条新闻的原始材料。",
                summary_zh=(
                    f"这是一条仅供本地页面验证的已润色{label}新闻摘要。"
                    "它不调用外部采集或模型服务，并保留真实页面所需的展示字段。"
                ),
                category=category,
                tags=[category, "local-demo"],
                title_similarity_key=f"local-demo-{category}-{position}",
                title_similarity_tokens=["local", "demo", category, str(position)],
                source_trust="established",
                verification_status="source_reported",
                corroborating_sources=["local-demo"],
                score=SEED_ITEMS_PER_CATEGORY - position,
                published_at=published_at - timedelta(minutes=category_index * 10 + position),
            )
            session.add(news)
            session.flush()
            session.add(
                NewsPolish(
                    news_item_id=news.id,
                    model="local-demo",
                    prompt_version=PROMPT_VERSION,
                    content_zh=news.summary_zh,
                    usage_json={"status": "flash", "reason": "development seed"},
                )
            )
            session.add(
                PublicNewsSelection(
                    batch_id=batch.id,
                    news_item_id=news.id,
                    category=category,
                    position=position,
                    selection_reason={"policy": SEED_POLICY_VERSION, "source_category": category},
                    polish_status="succeeded",
                )
            )
            if position == 1:
                all_items.append(news)

    for position, news in enumerate(all_items, start=1):
        session.add(
            PublicNewsSelection(
                batch_id=batch.id,
                news_item_id=news.id,
                category="all",
                position=position,
                selection_reason={"policy": SEED_POLICY_VERSION, "source_category": news.category},
                polish_status="succeeded",
            )
        )
    session.flush()
    return batch
