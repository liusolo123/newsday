"""Regression baseline for durable public-news display snapshots."""

from datetime import datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, PublicNewsBatch, PublicNewsSelection
from app.services.news import ingest_item
from finnews.sources.base import RawItem


class PublicNewsSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = Session(engine, expire_on_commit=False)
        self.now = datetime(2026, 9, 7, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.session.close()

    def _news(self, number: int):
        news = ingest_item(
            self.session,
            RawItem(
                source="test",
                title=f"AI 展示新闻 {number}",
                summary="用于公开展示快照的可审阅材料。",
                url=f"https://example.com/publication/{number}",
                published_at=self.now,
            ),
        )
        self.session.flush()
        return news

    def _batch(self) -> PublicNewsBatch:
        batch = PublicNewsBatch(
            deficits={"sports": {"target": 10, "actual": 2, "reason": "source_shortage"}}
        )
        self.session.add(batch)
        self.session.flush()
        return batch

    def test_snapshot_preserves_ranked_category_and_all_memberships(self) -> None:
        first = self._news(1)
        second = self._news(2)
        batch = self._batch()
        batch.selections.extend(
            [
                PublicNewsSelection(
                    news_item_id=first.id,
                    category="ai",
                    position=1,
                    selection_reason={"score": 9, "fresh": True},
                ),
                PublicNewsSelection(
                    news_item_id=first.id,
                    category="all",
                    position=1,
                    selection_reason={"diversity": True},
                ),
                PublicNewsSelection(
                    news_item_id=second.id,
                    category="ai",
                    position=2,
                    polish_status="succeeded",
                ),
            ]
        )
        self.session.commit()

        stored = self.session.get(PublicNewsBatch, batch.id)
        self.assertEqual(stored.status, "selecting")
        self.assertEqual(stored.target_count, 10)
        self.assertEqual(stored.deficits["sports"]["actual"], 2)
        self.assertEqual(
            [(item.category, item.position) for item in stored.selections],
            [("ai", 1), ("all", 1), ("ai", 2)],
        )
        self.assertEqual(first.publication_selections[0].batch_id, batch.id)

    def test_snapshot_rejects_duplicate_position_inside_a_category(self) -> None:
        batch = self._batch()
        batch.selections.extend(
            [
                PublicNewsSelection(news_item_id=self._news(1).id, category="ai", position=1),
                PublicNewsSelection(news_item_id=self._news(2).id, category="ai", position=1),
            ]
        )
        with self.assertRaises(IntegrityError):
            self.session.commit()

    def test_snapshot_rejects_duplicate_news_inside_a_category(self) -> None:
        batch = self._batch()
        news = self._news(1)
        batch.selections.extend(
            [
                PublicNewsSelection(news_item_id=news.id, category="ai", position=1),
                PublicNewsSelection(news_item_id=news.id, category="ai", position=2),
            ]
        )
        with self.assertRaises(IntegrityError):
            self.session.commit()

    def test_snapshot_enforces_categories_statuses_and_ten_item_boundary(self) -> None:
        batch = self._batch()
        self.session.add(PublicNewsSelection(news_item_id=self._news(1).id, category="ai", position=11))
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

        invalid_batch = PublicNewsBatch(status="unknown")
        self.session.add(invalid_batch)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

        invalid_selection = PublicNewsSelection(
            batch_id=batch.id,
            news_item_id=self._news(2).id,
            category="unknown",
            position=1,
        )
        self.session.add(invalid_selection)
        with self.assertRaises(IntegrityError):
            self.session.commit()


if __name__ == "__main__":
    unittest.main()
