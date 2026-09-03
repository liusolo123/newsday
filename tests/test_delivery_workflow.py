"""End-to-end delivery workflow checks with no outbound network requests."""

import base64
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.models import Base, DeliveryAttempt, DeliveryJob, NewsPolish, User
from app.services.deliveries import generate_due_jobs
from app.services.destinations import save_destination
from app.services.news import ingest_item
from app.services.subscriptions import save_subscription
from app.workers.dispatch import dispatch_once
from finnews.sources.base import RawItem


class DeliveryWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = Session(engine, expire_on_commit=False)
        self.encryption_key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
        user = User(
            username="workflow-user",
            normalized_username="workflow-user",
            password_hash=hash_password("a secure password"),
            recovery_code_hash=hash_password("another secure password"),
        )
        self.session.add(user)
        self.session.commit()
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        self.subscription = save_subscription(
            self.session, user.id, {"ai": 5}, [now.strftime("%H:%M")]
        )
        self.destination = save_destination(
            self.session,
            user.id,
            "feishu",
            "https://open.feishu.cn/open-apis/bot/v2/hook/example",
            self.encryption_key,
        )
        self.destination.verified_at = datetime.now(timezone.utc)
        ingest_item(
            self.session,
            RawItem(
                source="google_ai",
                title="AI workflow headline",
                summary="A source item used for a local delivery workflow test.",
                url="https://example.com/news/ai-workflow",
            ),
        )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()

    def _create_due_job(self) -> DeliveryJob:
        now = datetime.now(timezone.utc)
        self.assertEqual(generate_due_jobs(self.session, now), 1)
        self.session.commit()
        return self.session.query(DeliveryJob).one()

    def test_due_subscription_is_polished_sent_and_recorded(self) -> None:
        job = self._create_due_job()
        with patch("app.workers.dispatch.send_webhook") as send:
            self.assertEqual(dispatch_once(self.session, api_key="", encryption_key=self.encryption_key), 1)

        self.session.expire_all()
        delivered = self.session.get(DeliveryJob, job.id)
        self.assertEqual(delivered.status, "sent")
        self.assertEqual(delivered.attempts, 1)
        self.assertEqual(self.session.query(DeliveryAttempt).one().status, "sent")
        self.assertEqual(self.session.query(NewsPolish).count(), 1)
        self.assertEqual(send.call_args.args[0], "feishu")
        self.assertIn("AI workflow headline", send.call_args.args[2])

    def test_network_failure_is_saved_for_retry_without_sending(self) -> None:
        job = self._create_due_job()
        with patch("app.workers.dispatch.send_webhook", side_effect=requests.ConnectionError()):
            dispatch_once(self.session, api_key="", encryption_key=self.encryption_key)

        self.session.expire_all()
        delayed = self.session.get(DeliveryJob, job.id)
        attempt = self.session.query(DeliveryAttempt).one()
        self.assertEqual(delayed.status, "retrying")
        self.assertEqual(attempt.status, "retrying")
        self.assertEqual(attempt.error_code, "network_error")


if __name__ == "__main__":
    unittest.main()
