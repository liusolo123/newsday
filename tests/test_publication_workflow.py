"""Regression coverage for the select-then-polish public-news workflow."""

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, NewsPolish
from app.services.news import ingest_item
from app.services.polish import PROMPT_VERSION, polish_news
from app.services.publication_snapshots import freeze_public_news_batch
from app.services.publication_workflow import process_public_news_batch
from finnews.sources.base import RawItem
from llm_polish import PolishResult


class PublicNewsWorkflowTests(unittest.TestCase):
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

    def _batch(self, count: int = 2):
        headlines = ("AI 模型能力更新", "AI 芯片产品发布")
        for number in range(1, count + 1):
            item = ingest_item(
                self.session,
                RawItem(
                    source="google_ai",
                    title=headlines[number - 1],
                    summary="用于测试公开批次润色流程的可审阅材料。",
                    url=f"https://example.com/public-ai/{number}",
                    published_at=self.now,
                ),
                score=10 - number,
            )
            item.category = "ai"
        self.session.flush()
        return freeze_public_news_batch(self.session, now=self.now, categories=("ai",))

    def test_each_frozen_news_item_is_polished_once_across_all_memberships(self) -> None:
        batch = self._batch(2)
        successful = PolishResult("该新闻材料已完成中文润色，并仅保留原始材料支持的事实内容。", "flash")
        with patch("app.services.publication_workflow.polish_news", return_value=successful) as polish:
            result = process_public_news_batch(self.session, batch.id, api_key="test-key")

        self.assertEqual(polish.call_count, 2)
        self.assertEqual(result.status, "ready")
        self.assertTrue(all(selection.polish_status == "succeeded" for selection in result.selections))

    def test_failed_polish_keeps_batch_unready_and_records_each_membership(self) -> None:
        batch = self._batch(2)
        results = [
            PolishResult("第一条新闻材料已完成中文润色，并保留原始材料中的事实信息。", "flash"),
            PolishResult("润色服务暂不可用，请查看原文。", "fallback", "timeout"),
        ]
        with patch("app.services.publication_workflow.polish_news", side_effect=results):
            result = process_public_news_batch(self.session, batch.id, api_key="test-key")

        self.assertEqual(result.status, "failed")
        self.assertEqual(sum(selection.polish_status == "failed" for selection in result.selections), 2)
        self.assertEqual(sum(selection.polish_status == "succeeded" for selection in result.selections), 2)

    def test_successful_summary_cache_is_shared_but_fallback_is_retried(self) -> None:
        item = ingest_item(
            self.session,
            RawItem(
                source="google_ai",
                title="共享摘要缓存测试",
                summary="这是一段用于检查公共摘要缓存行为的材料。",
                url="https://example.com/cache-behavior",
                published_at=self.now,
            ),
        )
        success = PolishResult("该材料已经生成可复用的中文摘要，且未增加原始材料之外的事实信息。", "flash")
        with patch("app.services.polish.polish_item", return_value=success) as call_model:
            polish_news(self.session, item, api_key="test-key")
            polish_news(self.session, item, api_key="test-key")
        self.assertEqual(call_model.call_count, 1)

        fallback = PolishResult("润色服务暂不可用，请通过原文链接查看详情。", "fallback", "missing key")
        item_two = ingest_item(
            self.session,
            RawItem(
                source="google_ai",
                title="失败摘要重试测试",
                summary="这是一段用于检查失败摘要重试的材料。",
                url="https://example.com/cache-retry",
                published_at=self.now,
            ),
        )
        repaired = PolishResult("该材料已在后续重试中生成中文摘要，并保留原始材料支持的事实内容。", "pro")
        with patch("app.services.polish.polish_item", side_effect=(fallback, repaired)) as call_model:
            polish_news(self.session, item_two, api_key="")
            polish_news(self.session, item_two, api_key="test-key")
        stored = self.session.query(NewsPolish).filter_by(news_item_id=item_two.id, prompt_version=PROMPT_VERSION).one()
        self.assertEqual(call_model.call_count, 2)
        self.assertEqual(stored.usage_json["status"], "pro")


if __name__ == "__main__":
    unittest.main()
