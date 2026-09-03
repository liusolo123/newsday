"""Reliability guarantees for locking, retries, configuration changes, and deduplication."""

import base64
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.models import Base, DeliveryAttempt, DeliveryItem, DeliveryJob, User
from app.services.dashboard import set_subscription_enabled
from app.services.deliveries import (
    RETRY_DELAYS,
    claim_due_jobs,
    create_delivery_job,
    recover_stale_sending_jobs,
    render_delivery,
    retry_or_fail,
)
from app.services.destinations import save_destination
from app.services.news import ingest_item
from app.services.subscriptions import save_subscription
from app.workers.dispatch import dispatch_once
from finnews.sources.base import RawItem


class DeliveryReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = Session(engine, expire_on_commit=False)
        self.now = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
        self.key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
        self.user = User(
            username="reliability-user",
            normalized_username="reliability-user",
            password_hash=hash_password("a secure password"),
            recovery_code_hash=hash_password("another secure password"),
        )
        self.session.add(self.user)
        self.session.commit()
        self.subscription = save_subscription(self.session, self.user.id, {"ai": 5}, ["08:00"])
        self.destination = save_destination(
            self.session,
            self.user.id,
            "feishu",
            "https://open.feishu.cn/open-apis/bot/v2/hook/reliability-test",
            self.key,
            verified=True,
        )
        for number in range(10):
            ingest_item(
                self.session,
                RawItem(
                    source="google_ai",
                    title=f"AI reliability item {number}",
                    summary="Test material for a distinct delivery item.",
                    url=f"https://example.com/reliability/{number}",
                    published_at=self.now,
                ),
                score=10 - number,
            )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()

    def _job(self, scheduled_for: datetime | None = None) -> DeliveryJob:
        job = create_delivery_job(
            self.session,
            self.subscription,
            self.destination.id,
            scheduled_for or self.now,
        )
        self.assertIsNotNone(job)
        self.session.commit()
        return job

    def test_retries_three_times_after_initial_attempt_then_fails(self) -> None:
        job = self._job(self.now - timedelta(minutes=1))
        for attempt in range(1, len(RETRY_DELAYS) + 2):
            claimed = claim_due_jobs(self.session, self.now + timedelta(minutes=20 * attempt))
            self.assertEqual([item.id for item in claimed], [job.id])
            retry_or_fail(self.session, job, self.now + timedelta(minutes=20 * attempt), "network_error")
            self.session.commit()
            expected = "retrying" if attempt <= len(RETRY_DELAYS) else "failed"
            self.assertEqual(job.status, expected)
        self.assertEqual(job.attempts, 4)
        self.assertEqual(self.session.query(DeliveryAttempt).count(), 4)

    def test_stale_sending_lock_is_recovered_and_claimed_once(self) -> None:
        job = self._job(self.now - timedelta(hours=1))
        job.status = "sending"
        job.attempts = 1
        job.locked_at = self.now - timedelta(minutes=16)
        self.session.commit()

        self.assertEqual(recover_stale_sending_jobs(self.session, self.now), 1)
        self.assertEqual(job.status, "retrying")
        self.assertIsNone(job.locked_at)
        self.assertEqual(claim_due_jobs(self.session, self.now), [job])
        self.assertEqual(claim_due_jobs(self.session, self.now), [])
        self.assertEqual(self.session.query(DeliveryAttempt).one().error_code, "stale_sending_lock")

    def test_later_same_day_delivery_excludes_items_already_sent(self) -> None:
        first = self._job(datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc))
        first.status = "sent"
        first.attempts = 1
        self.session.commit()
        first_item_ids = set(self.session.scalars(select(DeliveryItem.news_item_id).where(DeliveryItem.delivery_job_id == first.id)))

        second = self._job(datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc))
        second_item_ids = set(self.session.scalars(select(DeliveryItem.news_item_id).where(DeliveryItem.delivery_job_id == second.id)))

        self.assertEqual(len(first_item_ids), 5)
        self.assertEqual(len(second_item_ids), 5)
        self.assertTrue(first_item_ids.isdisjoint(second_item_ids))

        second.status = "sent"
        self.session.commit()
        shortfall = self._job(datetime(2026, 9, 4, 12, 30, tzinfo=timezone.utc))
        self.assertIn("少于设定的 5 条", render_delivery(self.session, shortfall, api_key=""))

    def test_pause_and_configuration_change_cancel_only_unclaimed_future_jobs(self) -> None:
        future = self._job(self.now + timedelta(hours=2))
        self.assertTrue(set_subscription_enabled(self.session, self.user.id, False, now=self.now))
        self.session.commit()
        self.assertEqual(future.status, "cancelled")

        self.subscription.enabled = True
        changed = self._job(self.now + timedelta(hours=3))
        save_subscription(self.session, self.user.id, {"github": 5}, ["18:00"], now=self.now)
        self.session.commit()
        self.assertEqual(changed.status, "cancelled")

    def test_dispatch_cancels_a_job_if_subscription_is_disabled_after_claim(self) -> None:
        job = self._job(datetime(2020, 1, 1, tzinfo=timezone.utc))
        self.subscription.enabled = False
        self.session.commit()

        with patch("app.workers.dispatch.send_webhook") as send:
            self.assertEqual(dispatch_once(self.session, api_key="", encryption_key=self.key), 1)
        self.assertEqual(job.status, "cancelled")
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
