"""End-to-end checks for invitation, registration, login, and dashboard pages."""

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.invites import create_invite_code
from app.config import Settings
from app.main import app
from app.models import Base
from app.services.news import ingest_item
from finnews.sources.base import RawItem


class AccountPageTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        app.state.settings = Settings("sqlite", "session-secret", "lookup-key", "webhook-key")
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

    def test_public_news_page_shows_pool_items_without_login(self) -> None:
        session = app.state.session_factory()
        ingest_item(session, RawItem(source="test", title="公开新闻", summary="材料", url="https://example.com/public"))
        session.commit()
        session.close()
        response = self.client.get("/zh/news/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("公开新闻", response.text)


if __name__ == "__main__":
    unittest.main()
