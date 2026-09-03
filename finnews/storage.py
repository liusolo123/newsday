"""SQLite persistence: storage, cross-source dedupe, history retention."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .sources.base import RawItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT DEFAULT '',
    url TEXT NOT NULL,
    url_key TEXT NOT NULL UNIQUE,
    score INTEGER DEFAULT 0,
    is_keyword_hit INTEGER DEFAULT 0,
    bucket TEXT DEFAULT '',
    published_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_created ON news(created_at DESC);
"""

_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _normalize_text(text: str) -> str:
    return "".join(_WORD_RE.findall((text or "").lower()))


def url_key(url: str, title: str) -> str:
    """Dedupe key: normalized URL if present, else normalized title."""
    if url:
        key = re.sub(r"^https?://", "", url.strip().lower())
        key = re.sub(r"(\?|#).*$", "", key)
        key = key.rstrip("/")
        if key:
            return key
    return _normalize_text(title)


def title_similarity_key(title: str) -> str:
    """Title-only key used to catch near-duplicate reports across sources."""
    norm = _normalize_text(title)
    if len(norm) >= 12:
        return norm[:12]
    return norm


class Storage:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def insert_new(self, items: list[RawItem], *, score: int = 0,
                   is_hit: bool = False, bucket: str = "") -> tuple[int, list[RawItem]]:
        """Insert only unseen items. Returns (inserted_count, inserted_items)."""
        inserted: list[RawItem] = []
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        existing_urls = self._existing_keys()
        for it in items:
            key = url_key(it.url, it.title)
            if key in existing_urls:
                continue
            try:
                self.conn.execute(
                    "INSERT INTO news(source, title, summary, url, url_key, score,"
                    " is_keyword_hit, bucket, published_at, created_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        it.source, it.title, it.summary, it.url, key,
                        score, int(is_hit), bucket,
                        it.published_at.isoformat() if it.published_at else now,
                        now,
                    ),
                )
                existing_urls.add(key)
                inserted.append(it)
            except sqlite3.IntegrityError:
                continue
        self.conn.commit()
        return len(inserted), inserted

    def _existing_keys(self) -> set[str]:
        rows = self.conn.execute("SELECT url_key FROM news").fetchall()
        return {r[0] for r in rows}

    def recent(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT source, title, summary, url, score, is_keyword_hit, bucket,"
            " published_at, created_at FROM news ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "source": r[0], "title": r[1], "summary": r[2], "url": r[3],
                "score": r[4], "is_keyword_hit": bool(r[5]), "bucket": r[6],
                "published_at": r[7], "created_at": r[8],
            }
            for r in rows
        ]

    def close(self):
        self.conn.close()
