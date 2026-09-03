"""End-to-end checks for invitation, registration, login, and dashboard pages."""

import unittest
import base64
from unittest.mock import patch

import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.invites import create_invite_code
from app.config import Settings
from app.main import app
from app.models import Base, Destination, InviteCode, User
from app.services.subscriptions import save_subscription
from app.services.news import ingest_item
from finnews.sources.base import RawItem


class AccountPageTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        app.state.settings = Settings(
            "sqlite", "session-secret", "lookup-key", base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
        )
        session = app.state.session_factory()
        session.add(create_invite_code("pages-2026", "lookup-key", max_uses=1))
        session.commit()
        session.close()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        del app.state.session_factory
        del app.state.settings

    def test_invitation_to_dashboard_flow(self) -> None:
        invite = self.client.get("/zh/invite/")
        csrf = self.client.cookies["newsday_csrf"]
        approved = self.client.post("/zh/invite/", data={"invite_code": "pages-2026", "csrf_token": csrf}, follow_redirects=False)
        self.assertEqual(approved.status_code, 303)
        register = self.client.get("/zh/register/")
        self.assertIn("创建账户", register.text)
        created = self.client.post("/zh/register/", data={"username": "reader", "password": "a secure password", "csrf_token": csrf})
        self.assertEqual(created.status_code, 200)
        self.assertIn("保存恢复码", created.text)
        dashboard = self.client.get("/zh/dashboard/")
        self.assertIn("你好，reader", dashboard.text)

    def test_login_page_is_available_in_english(self) -> None:
        response = self.client.get("/en/login/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sign in", response.text)

    def test_login_attempts_are_rate_limited(self) -> None:
        self.client.get("/zh/login/")
        csrf = self.client.cookies["newsday_csrf"]
        for _ in range(5):
            response = self.client.post("/zh/login/", data={"username": "unknown", "password": "incorrect password", "csrf_token": csrf})
            self.assertIn("用户名或密码不正确", response.text)
        blocked = self.client.post("/zh/login/", data={"username": "unknown", "password": "incorrect password", "csrf_token": csrf})
        self.assertIn("尝试过于频繁", blocked.text)

    def test_public_news_page_shows_pool_items_without_login(self) -> None:
        session = app.state.session_factory()
        ingest_item(session, RawItem(source="test", title="公开新闻", summary="材料", url="https://example.com/public"))
        session.commit()
        session.close()
        response = self.client.get("/zh/news/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("公开新闻", response.text)

    def test_admin_can_create_and_disable_invite(self) -> None:
        app.state.settings = Settings(
            database_url="sqlite",
            app_session_secret="session-secret",
            invite_lookup_key="lookup-key",
            webhook_encryption_key=base64.urlsafe_b64encode(b"k" * 32).decode("ascii"),
            admin_usernames="reader",
        )
        self.client.get("/zh/invite/")
        csrf = self.client.cookies["newsday_csrf"]
        self.client.post("/zh/invite/", data={"invite_code": "pages-2026", "csrf_token": csrf})
        self.client.post("/zh/register/", data={"username": "reader", "password": "a secure password", "csrf_token": csrf})

        page = self.client.get("/zh/admin/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("邀请码管理", page.text)
        self.client.post("/zh/admin/", data={"action": "create", "code": "second-invite", "max_uses": "2", "csrf_token": csrf})
        session = app.state.session_factory()
        invite = session.query(InviteCode).filter_by(used_count=0, max_uses=2).one()
        invite_id = invite.id
        session.close()
        self.client.post("/zh/admin/", data={"action": "disable", "invite_id": str(invite_id), "csrf_token": csrf})
        session = app.state.session_factory()
        self.assertFalse(session.get(InviteCode, invite_id).enabled)
        session.close()

    def test_admin_page_rejects_non_admin_user(self) -> None:
        response = self.client.get("/zh/admin/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/zh/")

    def test_admin_can_pause_and_resume_a_subscription(self) -> None:
        app.state.settings = Settings(
            database_url="sqlite", app_session_secret="session-secret", invite_lookup_key="lookup-key",
            webhook_encryption_key="webhook-key", admin_usernames="reader",
        )
        self.client.get("/zh/invite/")
        csrf = self.client.cookies["newsday_csrf"]
        self.client.post("/zh/invite/", data={"invite_code": "pages-2026", "csrf_token": csrf})
        self.client.post("/zh/register/", data={"username": "reader", "password": "a secure password", "csrf_token": csrf})
        session = app.state.session_factory()
        user = session.query(User).filter_by(normalized_username="reader").one()
        save_subscription(session, user.id, {"ai": 5}, ["08:00"])
        session.commit()
        user_id = user.id
        session.close()

        page = self.client.get("/zh/admin/")
        self.assertIn("订阅用户", page.text)
        self.client.post("/zh/admin/", data={"action": "set_subscription", "user_id": str(user_id), "subscription_enabled": "false", "csrf_token": csrf})
        session = app.state.session_factory()
        self.assertFalse(session.query(User).filter_by(id=user_id).one().subscription.enabled)
        session.close()

    def test_destination_test_success_saves_verified_webhook_only_after_delivery_test(self) -> None:
        self.client.get("/zh/invite/")
        csrf = self.client.cookies["newsday_csrf"]
        self.client.post("/zh/invite/", data={"invite_code": "pages-2026", "csrf_token": csrf})
        self.client.post("/zh/register/", data={"username": "reader", "password": "a secure password", "csrf_token": csrf})
        session = app.state.session_factory()
        user = session.query(User).filter_by(normalized_username="reader").one()
        save_subscription(session, user.id, {"ai": 5}, ["08:00"])
        session.commit()
        session.close()

        with patch("app.web_auth.send_test_webhook") as send:
            response = self.client.post("/zh/destination/", data={"kind": "feishu", "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/example", "action": "test_and_save", "csrf_token": csrf})
        self.assertIn("测试成功", response.text)
        send.assert_called_once()
        session = app.state.session_factory()
        destination = session.query(Destination).one()
        self.assertIsNotNone(destination.verified_at)
        self.assertNotIn("example", destination.webhook_ciphertext)
        session.close()

    def test_failed_destination_test_does_not_save_a_webhook(self) -> None:
        self.client.get("/zh/invite/")
        csrf = self.client.cookies["newsday_csrf"]
        self.client.post("/zh/invite/", data={"invite_code": "pages-2026", "csrf_token": csrf})
        self.client.post("/zh/register/", data={"username": "reader", "password": "a secure password", "csrf_token": csrf})
        session = app.state.session_factory()
        user = session.query(User).filter_by(normalized_username="reader").one()
        save_subscription(session, user.id, {"ai": 5}, ["08:00"])
        session.commit()
        session.close()

        with patch("app.web_auth.send_test_webhook", side_effect=requests.ConnectionError):
            response = self.client.post("/zh/destination/", data={"kind": "feishu", "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/example", "action": "test_and_save", "csrf_token": csrf})
        self.assertIn("无法完成操作", response.text)
        session = app.state.session_factory()
        self.assertEqual(session.query(Destination).count(), 0)
        session.close()

    def test_dashboard_can_cancel_subscription_and_remove_credentials(self) -> None:
        self.client.get("/zh/invite/")
        csrf = self.client.cookies["newsday_csrf"]
        self.client.post("/zh/invite/", data={"invite_code": "pages-2026", "csrf_token": csrf})
        self.client.post("/zh/register/", data={"username": "reader", "password": "a secure password", "csrf_token": csrf})
        session = app.state.session_factory()
        user = session.query(User).filter_by(normalized_username="reader").one()
        save_subscription(session, user.id, {"ai": 5}, ["08:00"])
        session.commit()
        session.close()

        response = self.client.post("/zh/dashboard/cancel/", data={"confirm_cancel": "yes", "delete_credentials": "yes", "csrf_token": csrf}, follow_redirects=True)
        self.assertIn("订阅已取消", response.text)
        session = app.state.session_factory()
        self.assertFalse(session.query(User).filter_by(normalized_username="reader").one().subscription.enabled)
        session.close()


if __name__ == "__main__":
    unittest.main()
