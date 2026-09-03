"""RSS-based sources: Google News finance section and Yahoo Finance news."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup

from .base import BaseSource, RawItem

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(" ", strip=True)

GOOGLE_FINANCE_RSS = (
    "https://news.google.com/rss/headlines/section/topic/BUSINESS"
    "?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
)

YAHOO_NEWS_RSS = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline"
    "?s=%5EGSPC,%5EIXIC,%5EDJI&region=US&lang=en-US"
)

CNBC_MARKETS_RSS = "https://www.cnbc.com/id/20910258/device/rss/rss.html"

MARKETWATCH_RSS = "https://feeds.marketwatch.com/marketwatch/topstories/"


class RssSource(BaseSource):
    """Generic RSS source."""

    name = "rss"
    url = ""

    def fetch(self) -> list[RawItem]:
        self._throttle()
        resp = self.session.get(self.url, timeout=20)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        items = []
        for entry in parsed.entries[:60]:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            dt = None
            if published:
                dt = datetime(*published[:6], tzinfo=timezone.utc)
            items.append(
                RawItem(
                    source=self.name,
                    title=entry.get("title", "").strip(),
                    summary=_strip_html(entry.get("summary", "")),
                    url=entry.get("link", "").strip(),
                    published_at=dt,
                )
            )
        return items


class GoogleNewsSource(RssSource):
    name = "google_news"
    weight = 2
    url = GOOGLE_FINANCE_RSS


class YahooFinanceSource(RssSource):
    name = "yahoo_finance"
    weight = 2
    url = YAHOO_NEWS_RSS


class CnbcMarketsSource(RssSource):
    name = "cnbc_markets"
    weight = 2
    url = CNBC_MARKETS_RSS


class MarketWatchSource(RssSource):
    name = "marketwatch"
    weight = 2
    url = MARKETWATCH_RSS
