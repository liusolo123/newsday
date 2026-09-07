"""Regression coverage for quality-gated per-category public candidates."""

from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services.news import ingest_item
from app.services.publication_candidates import (
    PUBLIC_NEWS_LIMIT,
    select_all_category_candidates,
    select_category_candidates,
)
from finnews.sources.base import RawItem


class PublicationCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = Session(engine, expire_on_commit=False)
        self.now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.session.close()

    def _news(
        self,
        category: str,
        number: int,
        *,
        age_hours: int,
        score: int = 0,
        source: str = "test",
        url: str | None = None,
    ):
        item = ingest_item(
            self.session,
            RawItem(
                source=source,
                title=f"{category} candidate {number}",
                summary="这是一段长度足够的可审阅候选新闻材料，可供中文摘要在不补充事实的前提下改写。",
                url=url if url is not None else f"https://example.com/{category}/{number}",
                published_at=self.now - timedelta(hours=age_hours),
            ),
            score=score,
        )
        item.category = category
        self.session.flush()
        return item

    def test_fresh_candidates_fill_before_older_windows(self) -> None:
        fresh = [self._news("ai", number, age_hours=number, score=number) for number in range(1, 7)]
        older = [self._news("ai", number + 10, age_hours=48, score=100 - number) for number in range(1, 5)]

        result = select_category_candidates(self.session, "ai", now=self.now)

        self.assertEqual(len(result.items), PUBLIC_NEWS_LIMIT)
        self.assertEqual({item.id for item in result.items[:6]}, {item.id for item in fresh})
        self.assertEqual({item.id for item in result.items[6:]}, {item.id for item in older})
        self.assertEqual(result.searched_hours, 72)
        self.assertIsNone(result.deficit)

    def test_shortage_never_uses_another_category_as_padding(self) -> None:
        sports = [self._news("sports", number, age_hours=2) for number in range(1, 3)]
        [self._news("ai", number, age_hours=2) for number in range(1, 13)]

        result = select_category_candidates(self.session, "sports", now=self.now)

        self.assertEqual({item.id for item in result.items}, {item.id for item in sports})
        self.assertEqual(result.deficit["actual"], 2)
        self.assertEqual(result.deficit["backfill_sources"], ["google_sports"])

    def test_known_generic_source_pages_are_not_eligible_candidates(self) -> None:
        generic_sina = self._news(
            "markets",
            1,
            age_hours=1,
            source="sina_live",
            url="https://finance.sina.com.cn/7x24/",
        )
        generic_eastmoney = self._news(
            "markets",
            2,
            age_hours=1,
            source="eastmoney_724",
            url="https://www.eastmoney.com/",
        )
        valid = self._news(
            "markets",
            3,
            age_hours=1,
            source="eastmoney_724",
            url="https://finance.eastmoney.com/a/202609071234567890.html",
        )

        result = select_category_candidates(self.session, "markets", now=self.now)

        self.assertEqual([item.id for item in result.items], [valid.id])
        self.assertNotIn(generic_sina.id, [item.id for item in result.items])
        self.assertNotIn(generic_eastmoney.id, [item.id for item in result.items])

    def test_source_summary_must_be_long_enough_to_support_polishing(self) -> None:
        insufficient = self._news("markets", 1, age_hours=1, score=10)
        insufficient.source_summary = "材料过短"
        sufficient = self._news("markets", 2, age_hours=1, score=9)
        sufficient.source_summary = "这是一段长度足够的候选新闻材料，可供严谨中文摘要在不补充事实的前提下改写。"
        self.session.flush()

        result = select_category_candidates(self.session, "markets", now=self.now)

        self.assertEqual([item.id for item in result.items], [sufficient.id])
        self.assertNotIn(insufficient.id, [item.id for item in result.items])

    def test_all_category_selection_keeps_each_shortage_independent(self) -> None:
        self._news("ai", 1, age_hours=1)
        self._news("sports", 1, age_hours=1)

        results = select_all_category_candidates(
            self.session, ("ai", "sports"), now=self.now, target_count=2
        )

        self.assertEqual(len(results["ai"].items), 1)
        self.assertEqual(len(results["sports"].items), 1)
        self.assertEqual(results["ai"].deficit["actual"], 1)
        self.assertEqual(results["sports"].deficit["actual"], 1)

    def test_selector_rejects_invalid_category_and_target(self) -> None:
        with self.assertRaises(ValueError):
            select_category_candidates(self.session, "unknown", now=self.now)
        with self.assertRaises(ValueError):
            select_category_candidates(self.session, "ai", now=self.now, target_count=11)


if __name__ == "__main__":
    unittest.main()
