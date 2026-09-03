"""东方财富 7x24 快讯 source (public API, no signing required).

Selected as the live fast-news source because the CLS telegraph API
now rejects requests with unknown signatures (10012 sign check failed).
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from .base import BaseSource, RawItem, SourceError

FAST_NEWS_API = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"


class Eastmoney724Source(BaseSource):
    name = "eastmoney_724"
    weight = 4

    def fetch(self) -> list[RawItem]:
        self._throttle()
        try:
            resp = self.session.get(
                FAST_NEWS_API,
                params={
                    "client": "web",
                    "biz": "web_724",
                    "fastColumn": "102",
                    "sortEnd": "",
                    "pageSize": "30",
                    "req_trace": "finnews",
                },
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise SourceError(f"{self.name}: {exc}") from exc
        if payload.get("code") != "1":
            raise SourceError(f"{self.name}: code={payload.get('code')}")
        items = []
        for row in (payload.get("data") or {}).get("fastNewsList") or []:
            title = (row.get("title") or "").strip()
            if not title:
                continue
            items.append(
                RawItem(
                    source=self.name,
                    title=title,
                    summary=(row.get("summary") or "").strip(),
                    url="https://www.eastmoney.com/",
                    published_at=_parse_ts(row.get("showTime")),
                )
            )
        return items


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
