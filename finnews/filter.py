"""Keyword filtering, macro/micro bucketing and importance scoring (rules)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from .sources.base import RawItem

MACRO_KEYWORDS = [
    "央行", "美联储", "利率", "降息", "降准", "汇率", "外汇", "GDP", "CPI", "PPI",
    "通胀", "通缩", "货币政策", "财政政策", "关税", "贸易战", "经济数据", "宏观",
    "出口", "PMI", "社融", "LPR", "国债", "国债收益率", "加息", "m2",
]

MICRO_KEYWORDS = [
    "公司", "财报", "业绩", "并购", "收购", "股价", "涨停", "跌停", "IPO",
    "上市", "回购", "减持", "增持", "个股", "板块", "市值", "盈利", "亏损",
    "研报", "评级", "营收", "净利润", "合同", "订单", "earnings", "m&a",
    "apple", "nvidia", "tesla", "微软", "苹果", "英伟达", "特斯拉",
]

_BUCKET_PENALTY = 0  # bucket match does not change raw score


@dataclass
class ScoredItem:
    title: str
    summary: str
    url: str
    source: str
    score: int = 0
    importance: str = "low"
    is_keyword_hit: bool = False
    bucket: str = ""  # "macro" | "micro" | ""
    matched_keywords: list[str] = field(default_factory=list)
    published_at: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source": self.source,
            "score": self.score,
            "importance": self.importance,
            "is_keyword_hit": self.is_keyword_hit,
            "bucket": self.bucket,
            "matched_keywords": self.matched_keywords,
            "published_at": self.published_at,
        }


def _hit_count(text: str, keywords: Iterable[str]) -> int:
    lowered = text.lower()
    return sum(1 for k in keywords if k.lower() in lowered)


def _classify(text: str) -> tuple[str, int, int]:
    macro = _hit_count(text, MACRO_KEYWORDS)
    micro = _hit_count(text, MICRO_KEYWORDS)
    if macro and macro >= micro:
        return "macro", macro, micro
    if micro:
        return "micro", macro, micro
    return "", 0, 0


def _importance(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def score_items(items: Iterable[RawItem], keywords: list[str],
                source_weights: dict[str, int]) -> list[ScoredItem]:
    now = datetime.now(timezone.utc)
    scored: list[ScoredItem] = []
    for it in items:
        text = f"{it.title} {it.summary}"
        hits = [k for k in keywords if k in text]
        bucket, macro_n, micro_n = _classify(text)
        score = source_weights.get(it.source, 1)
        score += min(len(hits), 3) * 3
        if macro_n:
            score += 1
        if micro_n:
            score += 1
        if it.published_at:
            age_h = (now - it.published_at).total_seconds() / 3600
            if age_h <= 3:
                score += 2
            elif age_h <= 24:
                score += 1
        scored.append(
            ScoredItem(
                title=it.title,
                summary=it.summary,
                url=it.url,
                source=it.source,
                score=score,
                importance=_importance(score),
                is_keyword_hit=bool(hits),
                bucket=bucket,
                matched_keywords=hits,
                published_at=it.published_at.isoformat() if it.published_at else "",
            )
        )
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def assemble_report(scored: list[ScoredItem], macro_top: int = 3,
                    micro_top: int = 3) -> dict:
    """Build the final report: keyword hits + macro top-N + micro top-N."""
    hits = [s for s in scored if s.is_keyword_hit]
    non_hits = [s for s in scored if not s.is_keyword_hit]
    macro_pick = [s for s in non_hits if s.bucket == "macro"][:macro_top]
    micro_pick = [s for s in non_hits if s.bucket == "micro"][:micro_top]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stats": {
            "total_fetched": len(scored),
            "keyword_hits": len(hits),
            "macro": len(macro_pick),
            "micro": len(micro_pick),
        },
        "keyword_hits": [s.to_dict() for s in hits],
        "macro_top": [s.to_dict() for s in macro_pick],
        "micro_top": [s.to_dict() for s in micro_pick],
    }
