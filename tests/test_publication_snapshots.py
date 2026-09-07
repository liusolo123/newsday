"""Regression coverage for freezing public-news category and all-feed lists."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, PublicNewsSelection
from app.services.news import ingest_item
from app.services.publication_snapshots import freeze_public_news_batch
from finnews.sources.base import RawItem


class PublicationSnapshotServiceTests(unittest.TestCase):
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

    def _news(self, category: str, number: int, *, score: int = 0, age_hours: int = 1):
        item = ingest_item(
            self.session,
            RawItem(
                source="test",
                title=f"{category} 展示候选 {number}",
                summary="这是一段用于冻结公开展示名单的完整新闻材料，可供中文摘要在不补充事实的前提下改写。",
                url=f"https://example.com/{category}/{number}",
                published_at=self.now - timedelta(hours=age_hours),
            ),
            score=score,
        )
        item.category = category
        self.session.flush()
        return item

    def _selections(self, batch_id, category: str):
        return list(
            self.session.scalars(
                select(PublicNewsSelection)
                .where(PublicNewsSelection.batch_id == batch_id, PublicNewsSelection.category == category)
                .order_by(PublicNewsSelection.position)
            )
        )

    def test_freeze_caps_category_lists_and_persists_shortages(self) -> None:
        ai = [self._news("ai", number, score=100 - number) for number in range(1, 13)]
        sports = [self._news("sports", number, score=20 - number) for number in range(1, 3)]

        batch = freeze_public_news_batch(
            self.session, now=self.now, categories=("ai", "sports")
        )
        self.session.commit()

        self.assertEqual(batch.status, "polishing")
        self.assertEqual([row.news_item_id for row in self._selections(batch.id, "ai")], [item.id for item in ai[:10]])
        self.assertEqual([row.news_item_id for row in self._selections(batch.id, "sports")], [item.id for item in sports])
        self.assertEqual(batch.deficits["sports"]["actual"], 2)

    def test_all_feed_uses_only_frozen_category_items_and_mixes_categories(self) -> None:
        ai = [self._news("ai", number, score=200 - number) for number in range(1, 12)]
        [self._news("technology", number, score=100 - number) for number in range(1, 5)]
        [self._news("markets", number, score=80 - number) for number in range(1, 4)]

        batch = freeze_public_news_batch(
            self.session, now=self.now, categories=("ai", "technology", "markets")
        )
        all_rows = self._selections(batch.id, "all")
        category_rows = [
            *self._selections(batch.id, "ai"),
            *self._selections(batch.id, "technology"),
            *self._selections(batch.id, "markets"),
        ]

        self.assertEqual(len(all_rows), 10)
        self.assertTrue({row.news_item_id for row in all_rows}.issubset({row.news_item_id for row in category_rows}))
        source_counts = Counter(row.selection_reason["source_category"] for row in all_rows)
        self.assertGreaterEqual(len(source_counts), 3)
        self.assertEqual(source_counts["ai"], 4)
        self.assertEqual(source_counts["technology"], 3)
        self.assertEqual(source_counts["markets"], 3)
        self.assertNotIn(ai[-1].id, {row.news_item_id for row in all_rows})

    def test_all_deficit_is_explicit_when_frozen_union_is_short(self) -> None:
        self._news("ai", 1, score=10)
        self._news("sports", 1, score=9)

        batch = freeze_public_news_batch(
            self.session, now=self.now, categories=("ai", "sports")
        )

        self.assertEqual(len(self._selections(batch.id, "all")), 2)
        self.assertEqual(batch.deficits["all"]["actual"], 2)
        self.assertEqual(batch.deficits["all"]["covered_categories"], ["ai", "sports"])

    def test_freeze_rejects_invalid_configuration_before_creating_a_batch(self) -> None:
        with self.assertRaises(ValueError):
            freeze_public_news_batch(self.session, now=self.now, categories=("ai", "ai"))
        with self.assertRaises(ValueError):
            freeze_public_news_batch(self.session, now=self.now, target_count=11)
        self.assertEqual(self.session.query(PublicNewsSelection).count(), 0)


if __name__ == "__main__":
    unittest.main()
