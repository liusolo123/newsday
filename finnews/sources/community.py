"""Direct public sources for developer communities and GitHub discovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
import requests

from .base import BaseSource, RawItem, SourceError


def _utc_from_unix(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


class GitHubTrendingSource(BaseSource):
    name = "github_trending"
    weight = 4
    url = "https://github.com/trending?since=daily"

    def fetch(self) -> list[RawItem]:
        self._throttle()
        try:
            response = self.session.get(self.url, timeout=20)
            response.raise_for_status()
        except requests.RequestException as error:
            raise SourceError(f"{self.name}: {error}") from error
        items = []
        for article in BeautifulSoup(response.text, "html.parser").select("article.Box-row"):
            link = article.select_one("h2 a[href]")
            if not link:
                continue
            repository = link.get_text(" ", strip=True).replace(" ", "")
            if not repository:
                continue
            description = article.select_one("p")
            items.append(
                RawItem(
                    source=self.name,
                    title=repository,
                    summary=description.get_text(" ", strip=True) if description else "",
                    url=f"https://github.com/{repository}",
                )
            )
        if not items:
            raise SourceError(f"{self.name}: empty page")
        return items


class GitHubSearchSource(BaseSource):
    name = "github_search"
    weight = 4
    url = "https://api.github.com/search/repositories"

    def fetch(self) -> list[RawItem]:
        self._throttle()
        since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        try:
            response = self.session.get(
                self.url,
                params={"q": f"created:>{since}", "sort": "stars", "order": "desc", "per_page": 20},
                headers={"Accept": "application/vnd.github+json"},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise SourceError(f"{self.name}: {error}") from error
        items = [
            RawItem(
                source=self.name,
                title=(row.get("full_name") or "").strip(),
                summary=(row.get("description") or "").strip(),
                url=(row.get("html_url") or "").strip(),
            )
            for row in payload.get("items", [])
            if row.get("full_name") and row.get("html_url")
        ]
        if not items:
            raise SourceError(f"{self.name}: empty response")
        return items


class HackerNewsSource(BaseSource):
    name = "hacker_news"
    weight = 3

    def fetch(self) -> list[RawItem]:
        self._throttle()
        try:
            ids = self.session.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
            ).json()[:15]
            items = []
            for item_id in ids:
                row = self.session.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json", timeout=10
                ).json()
                if not row or row.get("type") != "story" or not row.get("title"):
                    continue
                items.append(
                    RawItem(
                        source=self.name,
                        title=row["title"].strip(),
                        summary=(row.get("text") or "").strip(),
                        url=row.get("url") or f"https://news.ycombinator.com/item?id={item_id}",
                        published_at=_utc_from_unix(row.get("time")),
                    )
                )
            if items:
                return items
        except (requests.RequestException, ValueError, TypeError):
            pass
        try:
            payload = self.session.get(
                "https://hn.algolia.com/api/v1/search", params={"tags": "front_page", "hitsPerPage": 15}, timeout=15
            ).json()
        except (requests.RequestException, ValueError) as error:
            raise SourceError(f"{self.name}: {error}") from error
        items = [
            RawItem(
                source=self.name,
                title=(row.get("title") or "").strip(),
                summary=(row.get("story_text") or "").strip(),
                url=row.get("url") or f"https://news.ycombinator.com/item?id={row.get('objectID', '')}",
            )
            for row in payload.get("hits", [])
            if row.get("title")
        ]
        if not items:
            raise SourceError(f"{self.name}: both endpoints returned no items")
        return items


class LobstersSource(BaseSource):
    name = "lobsters"
    weight = 3

    def fetch(self) -> list[RawItem]:
        self._throttle()
        try:
            payload = self.session.get("https://lobste.rs/hottest.json", timeout=15).json()
        except (requests.RequestException, ValueError) as error:
            raise SourceError(f"{self.name}: {error}") from error
        items = [
            RawItem(
                source=self.name,
                title=(row.get("title") or "").strip(),
                summary=(row.get("description") or "").strip(),
                url=(row.get("url") or row.get("short_id_url") or "").strip(),
            )
            for row in payload[:15]
            if row.get("title") and (row.get("url") or row.get("short_id_url"))
        ]
        if not items:
            raise SourceError(f"{self.name}: empty response")
        return items
