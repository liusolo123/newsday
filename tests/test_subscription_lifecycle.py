"""Subscription cancellation, credential deletion, and password-change coverage."""

import base64
from datetime import datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.models import Base, DeliveryJob, Destination, User
from app.services.accounts import AuthenticationError, change_password, create_login_session, current_user
from app.services.dashboard import cancel_subscription, dashboard_summary
from app.services.destinations import remove_destination_credentials, save_destination
from app.services.subscriptions import save_subscription


class SubscriptionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = Session(engine, expire_on_commit=False)
        self.key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
        self.user = User(
            username="lifecycle-user",
            normalized_username="lifecycle-user",
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
            "https://open.feishu.cn/open-apis/bot/v2/hook/example-token",
            self.key,
            verified=True,
        )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()

    def test_password_change_revokes_existing_sessions(self) -> None:
        old_token = create_login_session(self.session, "lifecycle-user", "a secure password")
        self.session.commit()

        changed = change_password(self.session, self.user.id, "a secure password", "a replacement password")
        new_token = create_login_session(self.session, changed.username, "a replacement password")
        self.session.commit()

        self.assertIsNone(current_user(self.session, old_token))
        self.assertEqual(current_user(self.session, new_token).id, self.user.id)
        with self.assertRaises(AuthenticationError):
            change_password(self.session, self.user.id, "incorrect password", "another replacement password")

    def test_cancellation_stops_pending_work_and_can_delete_credentials(self) -> None:
        for index, status in enumerate(("pending", "retrying"), start=1):
            self.session.add(
                DeliveryJob(
                    subscription_id=self.subscription.id,
                    destination_id=self.destination.id,
                    scheduled_for=datetime(2026, 9, index, tzinfo=timezone.utc),
                    next_attempt_at=datetime(2026, 9, index, tzinfo=timezone.utc),
                    status=status,
                    idempotency_key=f"job-{index}",
                )
            )
        self.session.commit()

        self.assertTrue(cancel_subscription(self.session, self.user.id, delete_credentials=True))
        self.session.commit()

        self.assertFalse(self.session.get(type(self.subscription), self.subscription.id).enabled)
        self.assertEqual({job.status for job in self.session.query(DeliveryJob).all()}, {"cancelled"})
        destination = self.session.get(Destination, self.destination.id)
        self.assertIsNone(destination.verified_at)
        self.assertIsNotNone(destination.credential_deleted_at)
        self.assertEqual(destination.webhook_ciphertext, "")
        self.assertEqual(destination.webhook_nonce, "")

    def test_dashboard_displays_only_masked_verified_destination(self) -> None:
        subscription, _, _ = dashboard_summary(self.session, self.user.id)
        self.assertEqual(subscription.destinations[0].webhook_masked, "open.feishu.cn/…-token")
        self.assertNotIn("https://", subscription.destinations[0].webhook_masked)

        self.assertEqual(remove_destination_credentials(self.session, self.user.id), 1)
        self.session.commit()
        subscription, next_time, _ = dashboard_summary(self.session, self.user.id)
        self.assertIsNone(next_time)
        self.assertIsNotNone(subscription.destinations[0].credential_deleted_at)


if __name__ == "__main__":
    unittest.main()
