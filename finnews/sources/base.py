"""Base source interface and unified data model."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def make_session(retries: int = 1, backoff: float = 0.5) -> requests.Session:
    """Session with automatic retry on 429/5xx and connection errors.
    retries=1 快速失败:源挂了只多等一次,不让重试拖慢整轮抓取。"""
    session = requests.Session()
    session.headers.setdefault("User-Agent", UA)
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(403, 429, 500, 502, 503, 504, 567),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


@dataclass
class RawItem:
    """Unified news item produced by any source."""

    source: str
    title: str
    summary: str = ""
    url: str = ""
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SourceError(Exception):
    """Raised when a source cannot be fetched at all."""


class BaseSource:
    """Base class for a news source. Subclasses implement `fetch`."""

    name = "base"
    weight = 1  # importance weight for scoring

    def __init__(self, session: requests.Session, interval: float = 1.5):
        self.session = session
        self.interval = interval
        session.headers.setdefault("User-Agent", UA)

    def fetch(self) -> list[RawItem]:  # pragma: no cover - interface
        raise NotImplementedError

    def _throttle(self):
        if self.interval > 0:
            time.sleep(self.interval)
