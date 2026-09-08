"""Tests for the auditable, deterministic historical link repair workflow."""

from datetime import datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, NewsItem
from app.services.source_link_repair import apply_source_link_repairs, plan_source_link_repairs


class SourceLinkRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = Session(engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.session.close()

    def _news(self, source: str, url: str, suffix: str) -> NewsItem:
        return NewsItem(
            source=source,
            canonical_url=url,
            url_hash=f"hash-{suffix}",
            title=f"新闻 {suffix}",
            source_summary="这是足够长的新闻原始摘要，用于链接修复测试。",
            summary_zh="这是足够长的新闻中文摘要，用于链接修复测试。",
            category="markets",
            published_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        )

    def test_plan_repairs_only_deterministic_wallstreet_legacy_links(self) -> None:
        legacy = self._news("wallstreetcn", "https://wallstreetcn.com/live/3161004", "legacy")
        self.session.add_all(
            [
                legacy,
                self._news("eastmoney_724", "https://www.eastmoney.com/", "eastmoney"),
                self._news("sina_live", "https://finance.sina.com.cn/7x24/", "sina"),
                self._news("google_ai", "https://example.com/article", "valid"),
            ]
        )
        self.session.commit()

        plan = plan_source_link_repairs(self.session)

        self.assertEqual(len(plan.repairs), 1)
        self.assertEqual(plan.repairs[0][0].id, legacy.id)
        self.assertEqual(plan.repairs[0][1], "https://wallstreetcn.com/livenews/3161004")
        self.assertEqual(plan.invalid_unrepairable, 2)
        self.assertEqual(plan.unchanged, 1)
        self.assertEqual(legacy.canonical_url, "https://wallstreetcn.com/live/3161004")

    def test_apply_uses_the_reviewed_plan_only(self) -> None:
        legacy = self._news("wallstreetcn", "https://www.wallstreetcn.com/live/42?ignored=yes", "apply")
        self.session.add(legacy)
        self.session.commit()

        applied = apply_source_link_repairs(self.session, plan_source_link_repairs(self.session))
        self.session.commit()

        self.assertEqual(applied, 1)
        self.assertEqual(legacy.canonical_url, "https://wallstreetcn.com/livenews/42")


if __name__ == "__main__":
    unittest.main()
