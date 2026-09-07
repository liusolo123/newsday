"""Regression coverage for deterministic local public-news seed data."""

from datetime import datetime, timezone
import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, PublicNewsSelection
from app.models.subscription import CATEGORY_VALUES
from app.services.dev_seed import SEED_ITEMS_PER_CATEGORY, seed_development_public_news
from app.services.publication_read import published_public_news


class DevelopmentSeedTests(unittest.TestCase):
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

    def test_seed_creates_ten_published_polished_items_for_each_category(self) -> None:
        batch = seed_development_public_news(
            self.session, now=datetime(2026, 9, 7, tzinfo=timezone.utc)
        )
        self.session.commit()

        for category in CATEGORY_VALUES:
            snapshot = published_public_news(self.session, category)
            self.assertEqual(snapshot.batch.id, batch.id)
            self.assertEqual(len(snapshot.items), SEED_ITEMS_PER_CATEGORY)
            self.assertTrue(all(item.summary_zh.startswith("这是一条仅供本地页面验证") for item in snapshot.items))
        self.assertEqual(len(published_public_news(self.session).items), SEED_ITEMS_PER_CATEGORY)

    def test_seed_is_idempotent(self) -> None:
        first = seed_development_public_news(self.session)
        self.session.commit()
        second = seed_development_public_news(self.session)
        self.session.commit()

        count = self.session.scalar(select(func.count()).select_from(PublicNewsSelection))
        self.assertEqual(first.id, second.id)
        self.assertEqual(count, SEED_ITEMS_PER_CATEGORY * (len(CATEGORY_VALUES) + 1))
