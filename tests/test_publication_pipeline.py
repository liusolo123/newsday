"""Local end-to-end checks for public-news selection, polish, retry, and readiness."""

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, NewsPolish, PublicNewsBatch, PublicNewsSelection
from app.services.news import ingest_item
from app.workers.publication import prepare_public_news_batch
from finnews.sources.base import RawItem
from llm_polish import PolishResult


class PublicNewsPipelineTests(unittest.TestCase):
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

    def _add_candidates(self) -> None:
        for number, title in enumerate(("人工智能模型发布", "云计算芯片更新"), start=1):
            item = ingest_item(
                self.session,
                RawItem(
                    source="google_ai",
                    title=title,
                    summary="该材料用于公开新闻完整流程的本地验证，并包含可供模型改写的事实内容。",
                    url=f"https://example.com/pipeline/{number}",
                    published_at=self.now,
                ),
                score=10 - number,
            )
            item.category = "ai"
        self.session.commit()

    def _selections(self, batch_id):
        return list(
            self.session.scalars(
                select(PublicNewsSelection).where(PublicNewsSelection.batch_id == batch_id)
            )
        )

    def test_local_pipeline_readies_only_the_deduplicated_frozen_union(self) -> None:
        self._add_candidates()
        polished = PolishResult("该新闻已根据原始材料生成中文摘要，且未新增任何材料之外的事实信息。", "flash")

        with patch("app.services.polish.polish_item", return_value=polished) as call_model:
            batch = prepare_public_news_batch(self.session, api_key="test-key")

        selections = self._selections(batch.id)
        self.assertEqual(batch.status, "ready")
        self.assertEqual(len(selections), 4)
        self.assertTrue(all(selection.polish_status == "succeeded" for selection in selections))
        self.assertEqual(call_model.call_count, 2)
        self.assertEqual(self.session.query(NewsPolish).count(), 2)

    def test_failed_batch_retries_in_place_and_never_changes_previous_publish(self) -> None:
        previous = PublicNewsBatch(status="published")
        self.session.add(previous)
        self._add_candidates()
        failed = PolishResult("润色服务暂不可用，请通过原文链接查看详情。", "fallback", "timeout")

        with patch("app.services.polish.polish_item", return_value=failed):
            unsuccessful = prepare_public_news_batch(self.session, api_key="test-key")

        self.assertEqual(unsuccessful.status, "failed")
        self.assertEqual(self.session.get(PublicNewsBatch, previous.id).status, "published")
        self.assertEqual(self.session.query(PublicNewsBatch).count(), 2)

        polished = PolishResult("该新闻已在重试后完成中文摘要，且仅包含原始材料支持的事实信息。", "pro")
        with patch("app.services.polish.polish_item", return_value=polished) as call_model:
            retried = prepare_public_news_batch(self.session, api_key="test-key")

        self.assertEqual(retried.id, unsuccessful.id)
        self.assertEqual(retried.status, "ready")
        self.assertEqual(call_model.call_count, 2)
        self.assertEqual(self.session.query(PublicNewsBatch).count(), 2)
        self.assertEqual(self.session.get(PublicNewsBatch, previous.id).status, "published")


if __name__ == "__main__":
    unittest.main()
