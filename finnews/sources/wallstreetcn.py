"""华尔街见闻 (WallstreetCN) crawler via its public content API."""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from .base import BaseSource, RawItem, SourceError

LIVES_API = "https://api-one.wallstcn.com/apiv1/content/lives"
ARTICLES_API = "https://api-one.wallstcn.com/apiv1/content/articles"


class WallstreetCnSource(BaseSource):
    name = "wallstreetcn"
    weight = 4

    def fetch(self) -> list[RawItem]:
        items = self._fetch_lives()
        if not items:
            items = self._fetch_articles()
        if not items:
            raise SourceError(f"{self.name}: no items from lives/articles APIs")
        return items

    def _fetch_lives(self) -> list[RawItem]:
        self._throttle()
        try:
            resp = self.session.get(
                LIVES_API,
                params={"channel": "global-channel", "limit": "30"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return []
        items = []
        for row in (data.get("data") or {}).get("items") or []:
            title = (row.get("title") or "").strip()
            brief = (row.get("content_text") or "").strip()
            if not title and not brief:
                continue
            if not title:
                title = brief[:80]
            url = ""
            if row.get("id"):
                url = f"https://wallstreetcn.com/livenews/{row['id']}"
            items.append(
                RawItem(
                    source=self.name,
                    title=title,
                    summary=brief,
                    url=url,
                    published_at=_parse_ts(row.get("display_time")),
                )
            )
        return items

    def _fetch_articles(self) -> list[RawItem]:
        self._throttle()
        try:
            resp = self.session.get(
                ARTICLES_API,
                params={"channel": "global-channel", "limit": "30", "action": "down"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return []
        items = []
        for row in (data.get("data") or {}).get("items") or []:
            title = (row.get("title") or "").strip()
            if not title:
                continue
            uri = row.get("uri") or ""
            url = "https://wallstreetcn.com/articles/" + str(row.get("id")) if row.get("id") else uri
            items.append(
                RawItem(
                    source=self.name,
                    title=title,
                    summary=(row.get("summary") or "").strip(),
                    url=url,
                    published_at=_parse_ts(row.get("display_time")),
                )
            )
        return items


def _parse_ts(value) -> datetime | None:
    try:
        if value:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, TypeError):
        pass
    return None
