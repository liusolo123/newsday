"""News-pool ingestion is local, deduplicated, and Chinese-safe."""
import unittest
from datetime import datetime, timezone
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, NewsPolish
from app.services.news import classify_news, ingest_item, public_news
from app.services.polish import polish_for_delivery
from app.workers.ingest import ingest_batch
from app.services.retention import cleanup_expired_news
from finnews.sources.base import RawItem


class NewsPoolTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.session = Session(engine)

    def tearDown(self):
        self.session.close()

    def test_ingest_deduplicates_and_keeps_chinese_fallback(self):
        item = RawItem(source="github", title="GitHub AI project gains traction", summary="Open source tools", url="https://example.com/item?x=1", published_at=datetime.now(timezone.utc))
        first = ingest_item(self.session, item, score=5)
        self.session.commit()
        self.assertEqual(first.category, "ai")
        self.assertGreaterEqual(sum("\u4e00" <= char <= "\u9fff" for char in first.summary_zh), 10)
        self.assertIsNone(ingest_item(self.session, item, score=5))
        self.assertEqual(len(public_news(self.session)), 1)

    def test_rule_classification_uses_supported_categories(self):
        self.assertEqual(classify_news("微博热搜话题", ""), "social_trends")
        self.assertEqual(classify_news("未知的新技术", ""), "technology")

    def test_worker_uses_safe_chinese_fallback_without_an_api_call(self):
        item = RawItem(source="test", title="科技新闻标题", summary="简短材料", url="https://example.com/worker")
        self.assertEqual(ingest_batch(self.session, [item]), 1)
        self.assertIn("原始材料", public_news(self.session)[0].summary_zh)

    def test_delivery_polish_is_cached_after_first_request(self):
        news = ingest_item(self.session, RawItem(source="test", title="测试标题", summary="测试材料", url="https://example.com/cache"))
        first = polish_for_delivery(self.session, news, api_key="")
        self.session.commit()
        second = polish_for_delivery(self.session, news, api_key="")
        self.assertEqual(first, second)
        self.assertEqual(self.session.query(NewsPolish).count(), 1)

    def test_retention_previews_then_deletes_only_expired_news(self):
        old = RawItem(source="test", title="旧新闻", summary="材料", url="https://example.com/old", published_at=datetime.now(timezone.utc) - timedelta(days=8))
        fresh = RawItem(source="test", title="新新闻", summary="材料", url="https://example.com/fresh", published_at=datetime.now(timezone.utc))
        ingest_item(self.session, old); ingest_item(self.session, fresh); self.session.commit()
        self.assertEqual(cleanup_expired_news(self.session, apply=False)["news_items"], 1)
        self.assertEqual(cleanup_expired_news(self.session, apply=True)["news_items"], 1)
        self.session.commit()
        self.assertEqual(len(public_news(self.session)), 1)
