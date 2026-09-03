"""RSS sources for the public news pool, including category-specific feeds."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser
from bs4 import BeautifulSoup

from .base import BaseSource, RawItem

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(" ", strip=True)

GOOGLE_NEWS_BASE = "https://news.google.com/rss"


def google_news_topic_url(topic: str) -> str:
    return f"{GOOGLE_NEWS_BASE}/headlines/section/topic/{topic}?" + urlencode(
        {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    )


def google_news_search_url(query: str) -> str:
    return f"{GOOGLE_NEWS_BASE}/search?" + urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )


GOOGLE_FINANCE_RSS = google_news_topic_url("BUSINESS")

YAHOO_NEWS_RSS = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline"
    "?s=%5EGSPC,%5EIXIC,%5EDJI&region=US&lang=en-US"
)

CNBC_MARKETS_RSS = "https://www.cnbc.com/id/20910258/device/rss/rss.html"

MARKETWATCH_RSS = "https://feeds.marketwatch.com/marketwatch/topstories/"
GITHUB_BLOG_RSS = "https://github.blog/feed/"


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


class GoogleAiSource(RssSource):
    name = "google_ai"
    weight = 2
    url = google_news_search_url("artificial intelligence")


class GoogleTechnologySource(RssSource):
    name = "google_technology"
    weight = 2
    url = google_news_topic_url("TECHNOLOGY")


class GoogleConsumerElectronicsSource(RssSource):
    name = "google_consumer_electronics"
    weight = 2
    url = google_news_search_url("consumer electronics")


class GoogleBusinessSource(RssSource):
    name = "google_business"
    weight = 2
    url = google_news_topic_url("BUSINESS")


class GoogleMarketsSource(RssSource):
    name = "google_markets"
    weight = 2
    url = google_news_search_url("stock markets")


class GooglePoliticsSource(RssSource):
    name = "google_politics"
    weight = 2
    url = google_news_search_url("politics")


class GoogleSportsSource(RssSource):
    name = "google_sports"
    weight = 2
    url = google_news_topic_url("SPORTS")


class GoogleEntertainmentSource(RssSource):
    name = "google_entertainment"
    weight = 2
    url = google_news_topic_url("ENTERTAINMENT")


class GoogleSocialTrendsSource(RssSource):
    name = "google_social_trends"
    weight = 2
    url = google_news_search_url("social media trends")


class GitHubBlogSource(RssSource):
    name = "github_blog"
    weight = 3
    url = GITHUB_BLOG_RSS
