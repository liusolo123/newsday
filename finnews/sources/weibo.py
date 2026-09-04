"""Public Weibo hot-search source with a documented fallback endpoint."""

from __future__ import annotations

from urllib.parse import quote

import requests

from .base import BaseSource, RawItem, SourceError


class WeiboHotSource(BaseSource):
    name = "weibo_hot"
    weight = 3

    def fetch(self) -> list[RawItem]:
        self._throttle()
        attempts = (
            ("https://weibo.com/ajax/side/hotSearch", {"Referer": "https://weibo.com/"}, self._official_items),
            ("https://api.vvhan.com/api/hotlist/wbHot", {}, self._fallback_items),
        )
        for url, headers, parser in attempts:
            try:
                payload = self.session.get(url, headers=headers, timeout=15).json()
                items = parser(payload)
                if items:
                    return items
            except (requests.RequestException, ValueError, TypeError):
                continue
        raise SourceError(f"{self.name}: all public endpoints failed")

    def _official_items(self, payload: dict) -> list[RawItem]:
        return [
            self._item(row.get("word", ""), row.get("num", ""))
            for row in (payload.get("data") or {}).get("realtime", [])[:20]
            if row.get("word")
        ]

    def _fallback_items(self, payload: dict) -> list[RawItem]:
        return [
            RawItem(
                source=self.name,
                title=row["title"].strip(),
                summary=f"热度 {row.get('hot', '?')}",
                url=(row.get("url") or f"https://s.weibo.com/weibo?q=%23{quote(row['title'])}%23").strip(),
            )
            for row in payload.get("data", [])[:20]
            if row.get("title")
        ]

    def _item(self, title: str, heat: object) -> RawItem:
        return RawItem(
            source=self.name,
            title=title.strip(),
            summary=f"热度 {heat or '?'}",
            url=f"https://s.weibo.com/weibo?q=%23{quote(title)}%23",
        )
