"""财联社电报 (CLS telegraph) crawler.

Primary path: official nodeapi endpoint with the known MD5 signing scheme.
Fallback: parse the server-rendered telegraph page HTML.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from .base import BaseSource, RawItem, SourceError

TELEGRAPH_API = "https://www.cls.cn/nodeapi/updateTelegraphList"
TELEGRAPH_PAGE = "https://www.cls.cn/telegraph"
SALT = "8J8u1JLUZzwaIlXxs7xS"


def _sign(params: dict[str, str]) -> str:
    text = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.md5((text + SALT).encode()).hexdigest()


def _parse_ts(value) -> datetime | None:
    try:
        if value:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, TypeError):
        pass
    return None


class ClsTelegraphSource(BaseSource):
    name = "cls_telegraph"
    weight = 5

    def fetch(self) -> list[RawItem]:
        items = self._fetch_api()
        if not items:
            items = self._fetch_page()
        if not items:
            raise SourceError(f"{self.name}: both API and page parse failed")
        return items

    def _fetch_api(self) -> list[RawItem]:
        self._throttle()
        params = {
            "app": "CailianpressWeb",
            "category": "",
            "lastTime": "",
            "last_time": "",
            "os": "web",
            "refresh_type": "1",
            "rn": "30",
            "sv": "7.7.5",
        }
        params["sign"] = _sign(params)
        try:
            resp = self.session.get(TELEGRAPH_API, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return []
        roll = (data.get("data") or {}).get("roll_data")
        if not isinstance(roll, list):
            return []
        items = []
        for row in roll:
            title = (row.get("title") or "").strip()
            brief = (row.get("brief") or row.get("content") or "").strip()
            if not title and not brief:
                continue
            if not title:
                title = brief[:80]
            url = row.get("shareurl") or row.get("url") or ""
            if url and not url.startswith("http"):
                url = "https://www.cls.cn" + url
            items.append(
                RawItem(
                    source=self.name,
                    title=title,
                    summary=brief,
                    url=url,
                    published_at=_parse_ts(row.get("ctime")) or _parse_ts(row.get("created_at")),
                )
            )
        return items

    def _fetch_page(self) -> list[RawItem]:
        self._throttle()
        try:
            resp = self.session.get(TELEGRAPH_PAGE, timeout=20)
            resp.raise_for_status()
        except requests.RequestException:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for box in soup.select(".telegraph-content-box"):
            card = box.select_one(".telegraph-item")
            if not card:
                continue
            title_el = card.select_one(".telegraph-content-brief")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue
            link_el = card.select_one("a[href]")
            url = link_el["href"] if link_el else ""
            if url and url.startswith("/"):
                url = "https://www.cls.cn" + url
            items.append(RawItem(source=self.name, title=title, summary="", url=url))
            if len(items) >= 30:
                break
        return items


# Keep state-extraction helper available for potential future HTML variants.
def _extract_state_json(html: str) -> dict | None:
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;", html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
