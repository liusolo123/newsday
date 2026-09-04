"""Source registry: build all enabled sources."""

from __future__ import annotations

import requests

from .base import BaseSource
from .cls import ClsTelegraphSource
from .community import GitHubSearchSource, GitHubTrendingSource, HackerNewsSource, LobstersSource
from .eastmoney import Eastmoney724Source
from .sina import SinaLiveSource
from .rss import (
    CnbcMarketsSource,
    GitHubBlogSource,
    GoogleAiSource,
    GoogleBusinessSource,
    GoogleConsumerElectronicsSource,
    GoogleNewsSource,
    GoogleMarketsSource,
    GooglePoliticsSource,
    GoogleSocialTrendsSource,
    GoogleSportsSource,
    GoogleTechnologySource,
    GoogleEntertainmentSource,
    MarketWatchSource,
    YahooFinanceSource,
)
from .wallstreetcn import WallstreetCnSource
from .weibo import WeiboHotSource
from .technology import (
    ArsTechnicaRssSource,
    JiqizhixinRssSource,
    Kr36RssSource,
    OscnRssSource,
    PhoronixRssSource,
    TheVergeRssSource,
    VentureBeatRssSource,
)

REGISTRY: dict[str, type[BaseSource]] = {
    "google_news": GoogleNewsSource,
    "yahoo_finance": YahooFinanceSource,
    "cnbc_markets": CnbcMarketsSource,
    "marketwatch": MarketWatchSource,
    "cls_telegraph": ClsTelegraphSource,
    "eastmoney_724": Eastmoney724Source,
    "sina_live": SinaLiveSource,
    "wallstreetcn": WallstreetCnSource,
    "google_ai": GoogleAiSource,
    "google_technology": GoogleTechnologySource,
    "google_consumer_electronics": GoogleConsumerElectronicsSource,
    "google_business": GoogleBusinessSource,
    "google_markets": GoogleMarketsSource,
    "google_politics": GooglePoliticsSource,
    "google_sports": GoogleSportsSource,
    "google_entertainment": GoogleEntertainmentSource,
    "google_social_trends": GoogleSocialTrendsSource,
    "github_blog": GitHubBlogSource,
    "github_trending": GitHubTrendingSource,
    "github_search": GitHubSearchSource,
    "hacker_news": HackerNewsSource,
    "lobsters": LobstersSource,
    "weibo_hot": WeiboHotSource,
    "oschina_rss": OscnRssSource,
    "jiqizhixin_rss": JiqizhixinRssSource,
    "36kr_rss": Kr36RssSource,
    "venturebeat_rss": VentureBeatRssSource,
    "arstechnica_rss": ArsTechnicaRssSource,
    "phoronix_rss": PhoronixRssSource,
    "theverge_rss": TheVergeRssSource,
}


def build_sources(config: dict, session: requests.Session) -> list[BaseSource]:
    interval = float(config.get("request_interval", 1.5))
    sources = []
    enabled = (config.get("sources") or {})
    for name, cls in REGISTRY.items():
        if enabled.get(name, {}).get("enabled", False):
            sources.append(cls(session, interval=interval))
    return sources
