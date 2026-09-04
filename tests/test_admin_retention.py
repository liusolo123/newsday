"""Administrator controls and unified retention behavior."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.models import Base, DeliveryAttempt, DeliveryItem, DeliveryJob, Destination, User
from app.services.admin_dashboard import retry_failed_delivery, set_destination_enabled
from app.services.categories import category_presets, update_category_preset
from app.services.news import ingest_item
from app.services.retention import cleanup_expired_news
from app.services.subscriptions import SubscriptionValidationError, save_subscription
from finnews.sources.base import RawItem


class AdminRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = Session(engine, expire_on_commit=False)
        self.user = User(
            username="operator",
            normalized_username="operator",
            password_hash=hash_password("a secure password"),
            recovery_code_hash=hash_password("another secure password"),
        )
        self.session.add(self.user)
        self.session.commit()
        self.subscription = save_subscription(self.session, self.user.id, {"ai": 5}, ["08:00"])
        self.destination = Destination(
            subscription_id=self.subscription.id,
            kind="feishu",
            webhook_ciphertext="ciphertext",
            webhook_nonce="nonce",
            webhook_masked="masked",
        )
        self.session.add(self.destination)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()

    def test_category_presets_are_seeded_and_disabled_keys_reject_new_selection(self) -> None:
        self.assertEqual(len(category_presets(self.session)), 10)
        self.assertTrue(
            update_category_preset(
                self.session,
                "ai",
                label_zh="人工智能",
                label_en="Artificial intelligence",
                sort_order=1,
                enabled=False,
            )
        )
        # Existing users may retain the disabled preset until they remove it.
        save_subscription(self.session, self.user.id, {"ai": 5}, ["08:00"])
        second = User(
            username="new-reader",
            normalized_username="new-reader",
            password_hash=hash_password("a secure password"),
            recovery_code_hash=hash_password("another secure password"),
        )
        self.session.add(second)
        self.session.flush()
        with self.assertRaises(SubscriptionValidationError):
            save_subscription(self.session, second.id, {"ai": 5}, ["08:00"])

    def test_admin_can_retry_failed_work_and_disable_destination(self) -> None:
        now = datetime.now(timezone.utc)
        job = DeliveryJob(
            subscription_id=self.subscription.id,
            destination_id=self.destination.id,
            scheduled_for=now,
            next_attempt_at=now,
            status="failed",
            attempts=2,
            idempotency_key="a" * 64,
        )
        self.session.add(job)
        self.session.commit()
        self.assertTrue(retry_failed_delivery(self.session, job.id))
        self.assertEqual(job.status, "retrying")
        self.assertEqual(self.session.query(DeliveryAttempt).one().error_code, "admin_retry")
        self.assertTrue(set_destination_enabled(self.session, self.destination.id, False))
        self.assertFalse(self.destination.enabled)

    def test_dry_run_and_apply_clean_database_and_legacy_artifacts_without_job_audit_loss(self) -> None:
        now = datetime(2026, 9, 10, tzinfo=timezone.utc)
        old_news = ingest_item(
            self.session,
            RawItem(
                source="test",
                title="old content",
                summary="material",
                url="https://example.com/old-content",
                published_at=now - timedelta(days=8),
            ),
        )
        job = DeliveryJob(
            subscription_id=self.subscription.id,
            destination_id=self.destination.id,
            scheduled_for=now - timedelta(days=8),
            next_attempt_at=now - timedelta(days=8),
            status="sent",
            idempotency_key="b" * 64,
        )
        self.session.add(job)
        self.session.flush()
        self.session.add(DeliveryItem(delivery_job_id=job.id, news_item_id=old_news.id, position=1))
        self.session.commit()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "output").mkdir()
            legacy = root / "output" / "2026-09-02.md"
            legacy.write_text("old report", encoding="utf-8")
            preview = cleanup_expired_news(self.session, now=now, root=root)
            self.assertEqual(preview["news_items"], 1)
            self.assertEqual(preview["legacy_artifacts"], 1)
            self.assertTrue(legacy.exists())
            applied = cleanup_expired_news(self.session, now=now, root=root, apply=True)
            self.session.commit()
        self.assertEqual(applied["delivery_items"], 1)
        self.assertIsNotNone(self.session.get(DeliveryJob, job.id))
        self.assertFalse(legacy.exists())


if __name__ == "__main__":
    unittest.main()
