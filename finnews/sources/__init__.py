"""Source registry: build all enabled sources."""

from __future__ import annotations

import requests

from .base import BaseSource
from .cls import ClsTelegraphSource
from .eastmoney import Eastmoney724Source
from .sina import SinaLiveSource
from .rss import (
    CnbcMarketsSource,
    GoogleNewsSource,
    MarketWatchSource,
    YahooFinanceSource,
)
from .wallstreetcn import WallstreetCnSource

REGISTRY: dict[str, type[BaseSource]] = {
    "google_news": GoogleNewsSource,
    "yahoo_finance": YahooFinanceSource,
    "cnbc_markets": CnbcMarketsSource,
    "marketwatch": MarketWatchSource,
    "cls_telegraph": ClsTelegraphSource,
    "eastmoney_724": Eastmoney724Source,
    "sina_live": SinaLiveSource,
    "wallstreetcn": WallstreetCnSource,
}


def build_sources(config: dict, session: requests.Session) -> list[BaseSource]:
    interval = float(config.get("request_interval", 1.5))
    sources = []
    enabled = (config.get("sources") or {})
    for name, cls in REGISTRY.items():
        if enabled.get(name, {}).get("enabled", True):
            sources.append(cls(session, interval=interval))
    return sources
