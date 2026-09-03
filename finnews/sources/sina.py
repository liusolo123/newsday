"""新浪财经 7x24 快讯 source (public API, no signing required).

国内可达的实时财经快讯,用于补充 Google News 在被墙环境下的空缺。
接口: https://zhibo.sina.com.cn/api/zhibo/feed (zhibo_id=152 财经直播)
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from .base import BaseSource, RawItem, SourceError

FEED_API = "https://zhibo.sina.com.cn/api/zhibo/feed"


class SinaLiveSource(BaseSource):
    name = "sina_live"
    weight = 4

    def fetch(self) -> list[RawItem]:
        self._throttle()
        try:
            resp = self.session.get(
                FEED_API,
                params={
                    "page": 1,
                    "page_size": 30,
                    "zhibo_id": 152,
                    "tag_id": 0,
                    "dire": "f",
                    "dpc": 1,
                },
                headers={"Referer": "https://finance.sina.com.cn/7x24/"},
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise SourceError(f"{self.name}: {exc}") from exc

        feed = (payload.get("result") or {}).get("data", {}).get("feed", {})
        items = []
        for row in feed.get("list") or []:
            rich = row.get("rich_text") or ""
            if not rich:
                continue
            text = BeautifulSoup(rich, "html.parser").get_text(" ", strip=True)
            if not text:
                continue
            items.append(
                RawItem(
                    source=self.name,
                    title=text[:80],
                    summary=text,
                    url="https://finance.sina.com.cn/7x24/",
                    published_at=_parse_ts(row.get("create_time")),
                )
            )
        if not items:
            raise SourceError(f"{self.name}: empty feed")
        return items


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
