"""Regression tests for scoring, explainable classification, and source verification."""

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, NewsPolish
from app.services.news import classify_news, ingest_item, public_news, trust_notice
from app.services.polish import polish_for_delivery
from app.workers.ingest import fetch_and_ingest
from finnews.sources.base import RawItem
from llm_polish import PolishResult


class _Source:
    def __init__(self, name: str, weight: int, items: list[RawItem] | Exception):
        self.name = name
        self.weight = weight
        self.items = items

    def fetch(self) -> list[RawItem]:
        if isinstance(self.items, Exception):
            raise self.items
        return self.items


class ContentQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = Session(engine, expire_on_commit=False)
        self.now = datetime(2026, 9, 4, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.session.close()

    def _item(self, title: str, source: str, url: str) -> RawItem:
        return RawItem(source=source, title=title, summary="可审阅的新闻材料。", url=url, published_at=self.now)

    def test_exclusive_technology_classification_and_tags(self) -> None:
        self.assertEqual(
            classify_news("OpenAI 发布新模型", "", "google_technology"), "ai"
        )
        self.assertEqual(classify_news("GitHub AI 项目", ""), "github")
        self.assertEqual(
            classify_news("新款 iPhone 发布", "", "google_technology"),
            "consumer_electronics",
        )
        self.assertEqual(
            classify_news("数据库框架更新", "", "google_technology"), "technology"
        )
        news = ingest_item(
            self.session,
            self._item("OpenAI 发布新模型", "google_technology", "https://example.com/ai"),
        )
        self.assertEqual(news.category, "ai")
        self.assertIn("ai", news.tags)
        self.assertNotIn("technology", news.tags)

    def test_cross_source_title_similarity_deduplicates_and_corroborates(self) -> None:
        first = ingest_item(
            self.session,
            self._item("公司发布季度财报", "google_business", "https://example.com/a"),
            score=2,
        )
        self.assertEqual(first.verification_status, "needs_corroboration")
        self.assertIsNone(
            ingest_item(
                self.session,
                self._item("公司发布季度财报", "wallstreetcn", "https://example.org/b"),
                score=9,
            )
        )
        self.assertEqual(len(public_news(self.session)), 1)
        self.assertEqual(first.score, 9)
        self.assertEqual(first.verification_status, "corroborated")
        self.assertEqual(first.corroborating_sources, ["google_business", "wallstreetcn"])

    def test_similarity_rule_does_not_merge_distinct_apple_stories(self) -> None:
        ingest_item(
            self.session,
            self._item("苹果公司发布新款手机", "google_consumer_electronics", "https://example.com/phone"),
        )
        second = ingest_item(
            self.session,
            self._item("苹果公司公布季度财报", "google_business", "https://example.org/earnings"),
        )
        self.assertIsNotNone(second)
        self.assertEqual(len(public_news(self.session)), 2)

    def test_global_deduplication_applies_across_source_categories(self) -> None:
        ingest_item(
            self.session,
            self._item("新品发布会公布开发计划", "google_ai", "https://example.com/launch-a"),
        )
        self.assertIsNone(
            ingest_item(
                self.session,
                self._item(
                    "新品发布会公布开发计划",
                    "google_consumer_electronics",
                    "https://example.org/launch-b",
                ),
            )
        )
        pooled = public_news(self.session)
        self.assertEqual(len(pooled), 1)
        self.assertEqual(pooled[0].category, "ai")

    def test_generic_fast_news_urls_do_not_collapse_distinct_items(self) -> None:
        first = ingest_item(
            self.session,
            self._item("市场快讯一", "eastmoney_724", "https://www.eastmoney.com/"),
        )
        second = ingest_item(
            self.session,
            self._item("市场快讯二", "eastmoney_724", "https://www.eastmoney.com/"),
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)

    def test_duplicate_fast_news_upgrades_a_generic_link_to_a_detail_link(self) -> None:
        legacy = ingest_item(
            self.session,
            self._item("市场快讯", "eastmoney_724", "https://www.eastmoney.com/"),
        )
        self.assertIsNone(
            ingest_item(
                self.session,
                self._item(
                    "市场快讯",
                    "eastmoney_724",
                    "https://finance.eastmoney.com/a/202609071234567890.html",
                ),
            )
        )
        self.assertEqual(
            legacy.canonical_url,
            "https://finance.eastmoney.com/a/202609071234567890.html",
        )

    def test_fetch_scores_items_and_isolates_a_failed_source(self) -> None:
        high = self._item("重点市场新闻", "google_markets", "https://example.com/high")
        low = self._item("普通技术新闻", "google_technology", "https://example.com/low")
        sources = [
            _Source("google_markets", 4, [high]),
            _Source("google_technology", 1, [low]),
            _Source("unavailable", 1, RuntimeError("unavailable")),
        ]
        config = {"keywords": ["重点"], "max_per_source": 30}
        with patch("app.workers.ingest.load_config", return_value=config), patch(
            "app.workers.ingest.build_sources", return_value=sources
        ):
            inserted, failures = fetch_and_ingest(self.session, "unused.json")
        self.assertEqual(inserted, 2)
        self.assertEqual(len(failures), 1)
        ranked = public_news(self.session)
        self.assertEqual(ranked[0].title, "重点市场新闻")
        self.assertGreater(ranked[0].score, ranked[1].score)

    def test_risk_notice_and_delivery_usage_are_persisted_without_material(self) -> None:
        trend = ingest_item(
            self.session,
            self._item("微博热搜话题", "google_social_trends", "https://example.com/trend"),
        )
        self.assertIn("热搜不等于事实确认", trust_notice(trend))
        news = ingest_item(
            self.session,
            self._item("模型服务状态", "google_ai", "https://example.com/model"),
        )
        result = PolishResult(
            "模型服务提供了面向开发者的公开能力，材料未包含额外事实。",
            "flash",
            usage=(
                {
                    "model": "deepseek-v4-flash",
                    "prompt_tokens": 5,
                    "completion_tokens": 7,
                    "reasoning_tokens": 0,
                    "total_tokens": 12,
                },
            ),
        )
        with patch("app.services.polish.polish_item", return_value=result):
            polish_for_delivery(self.session, news, api_key="test-key")
        stored = self.session.query(NewsPolish).one()
        self.assertEqual(stored.model, "deepseek-v4-flash")
        self.assertEqual(stored.usage_json["status"], "flash")
        self.assertEqual(stored.usage_json["totals"]["total_tokens"], 12)


if __name__ == "__main__":
    unittest.main()
