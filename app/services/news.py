"""Ingest existing normalized source items into the public news pool."""

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from finnews.sources.base import RawItem
from finnews.storage import url_key
from llm_polish import chinese_fallback

from app.models import NewsItem
from app.models.subscription import CATEGORY_VALUES


CATEGORY_RULES = {
    "github": ("github", "repo", "开源项目"),
    "ai": ("人工智能", "大模型", "agent", "openai", "模型训练", "生成式"),
    "consumer_electronics": ("手机", "电脑", "iphone", "ipad", "wearable", "耳机", "芯片"),
    "markets": ("股", "基金", "债券", "汇率", "加密", "bitcoin", "行情"),
    "business": ("经济", "公司", "财报", "贸易", "宏观", "cpi"),
    "politics": ("政策", "外交", "政府", "选举"),
    "sports": ("比赛", "联赛", "足球", "篮球", "奥运"),
    "entertainment": ("电影", "音乐", "综艺", "游戏", "艺人"),
    "social_trends": ("热搜", "微博", "话题榜"),
}

SOURCE_CATEGORY_HINTS = {
    "google_ai": "ai",
    "google_consumer_electronics": "consumer_electronics",
    "google_business": "business",
    "google_markets": "markets",
    "google_politics": "politics",
    "google_sports": "sports",
    "google_entertainment": "entertainment",
    "google_social_trends": "social_trends",
    "github_blog": "github",
    "github_trending": "github",
    "github_search": "github",
    "weibo_hot": "social_trends",
    "eastmoney_724": "markets",
    "sina_live": "markets",
}

SOURCE_TRUST = {
    "github_blog": "primary",
    "github_trending": "primary",
    "github_search": "primary",
    "eastmoney_724": "established",
    "sina_live": "established",
    "wallstreetcn": "established",
}
HIGH_RISK_CATEGORIES = {"business", "markets", "politics"}
GENERIC_URL_SOURCES = {"eastmoney_724", "sina_live"}
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.#-]*")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def title_similarity_tokens(title: str) -> list[str]:
    """Return deterministic, reviewable title tokens for near-duplicate checks."""
    normalized = unicodedata.normalize("NFKC", title).casefold()
    tokens = {
        token
        for token in _LATIN_TOKEN_RE.findall(normalized)
        if len(token) > 1 or token.isdigit()
    }
    for run in _CJK_RUN_RE.findall(normalized):
        if len(run) <= 4:
            tokens.add(run)
        tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return sorted(tokens)


def title_similarity_key(tokens: list[str]) -> str:
    return hashlib.sha256("\x1f".join(tokens).encode("utf-8")).hexdigest()


def _similar_enough(left: list[str], right: list[str]) -> bool:
    left_set, right_set = set(left), set(right)
    overlap = left_set & right_set
    if len(overlap) < 2:
        return False
    return len(overlap) / len(left_set | right_set) >= 0.72


def _canonical_identity(item: RawItem) -> str:
    if item.source in GENERIC_URL_SOURCES:
        return url_key("", item.title)
    return url_key(item.url, item.title)


def _source_trust(source: str) -> str:
    return SOURCE_TRUST.get(source, "aggregator" if source.startswith("google_") else "reported")


def _verification_status(category: str, source_trust: str, source_count: int = 1) -> str:
    if category == "social_trends":
        return "unverified"
    if category in HIGH_RISK_CATEGORIES:
        return "corroborated" if source_count >= 2 else "needs_corroboration"
    if category == "entertainment":
        return "source_reported"
    return "source_reported" if source_trust != "primary" else "verified_source"


def generate_tags(title: str, summary: str, category: str, source: str) -> list[str]:
    text = f"{title} {summary}".casefold()
    tags = [category]
    for tag, keywords in CATEGORY_RULES.items():
        if tag != category and any(keyword in text for keyword in keywords):
            tags.append(tag)
    for keyword in ("openai", "github", "苹果", "iphone", "a股", "美股", "加密", "人工智能"):
        if keyword in text:
            tags.append(keyword)
    tags.append(source)
    return list(dict.fromkeys(tags))[:6]


def classify_news(title: str, summary: str, source: str = "") -> str:
    # Topic-specific sources are authoritative for their narrow topic. Generic
    # technology feeds are deliberately classified by the exclusive rules below.
    hinted_category = SOURCE_CATEGORY_HINTS.get(source)
    if hinted_category:
        return hinted_category
    text = f"{title} {summary}".lower()
    if source == "github_blog" or "github" in text:
        return "github"
    if re.search(r"(?<![a-z])(?:ai|llm|agent)(?![a-z])", text):
        return "ai"
    for category, keywords in CATEGORY_RULES.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "technology"


def trust_notice(news: NewsItem) -> str:
    if news.category == "social_trends":
        return "提示：热搜不等于事实确认，请以原始来源和后续权威信息为准。"
    if news.verification_status == "needs_corroboration":
        return "提示：该财经或时政信息目前仅有单一来源，仍待多源核验。"
    if news.category == "entertainment":
        return "提示：娱乐信息为来源报道，发布前请以原始来源为准。"
    return ""


def _merge_duplicate(existing: NewsItem, item: RawItem, score: int) -> None:
    sources = list(existing.corroborating_sources or [existing.source])
    if existing.source not in sources:
        sources.insert(0, existing.source)
    if item.source not in sources:
        sources.append(item.source)
    existing.corroborating_sources = sources
    existing.score = max(existing.score, score)
    existing.verification_status = _verification_status(
        existing.category, existing.source_trust, len(sources)
    )


def ingest_item(session: Session, item: RawItem, score: int = 0, summary_zh: str = "") -> Optional[NewsItem]:
    canonical_url = _canonical_identity(item)
    digest = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    existing_url = session.scalar(select(NewsItem).where(NewsItem.url_hash == digest))
    if existing_url:
        _merge_duplicate(existing_url, item, score)
        return None
    category = classify_news(item.title, item.summary, item.source)
    if category not in CATEGORY_VALUES:
        category = "technology"
    tokens = title_similarity_tokens(item.title)
    candidates = session.scalars(
        select(NewsItem).where(
            NewsItem.published_at >= (item.published_at or datetime.now(timezone.utc)) - timedelta(days=7)
        )
    )
    for candidate in candidates:
        candidate_tokens = candidate.title_similarity_tokens or title_similarity_tokens(candidate.title)
        if _similar_enough(tokens, candidate_tokens):
            _merge_duplicate(candidate, item, score)
            return None
    source_trust = _source_trust(item.source)
    news = NewsItem(source=item.source, canonical_url=item.url or canonical_url, url_hash=digest, title=item.title.strip(), source_summary=item.summary.strip(), summary_zh=summary_zh.strip() or chinese_fallback(), category=category, tags=generate_tags(item.title, item.summary, category, item.source), title_similarity_key=title_similarity_key(tokens), title_similarity_tokens=tokens, source_trust=source_trust, verification_status=_verification_status(category, source_trust), corroborating_sources=[item.source], score=score, published_at=item.published_at or datetime.now(timezone.utc))
    session.add(news)
    session.flush()
    return news


def public_news(session: Session, category: Optional[str] = None, limit: int = 30) -> list[NewsItem]:
    query = select(NewsItem).order_by(NewsItem.score.desc(), NewsItem.published_at.desc()).limit(limit)
    if category in CATEGORY_VALUES:
        query = query.where(NewsItem.category == category)
    return list(session.scalars(query))
