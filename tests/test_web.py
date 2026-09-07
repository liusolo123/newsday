"""Focused checks for public web routing and bilingual rendering."""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.auth.security import hash_opaque_token, hash_password
from app.models import AuthSession, Base, User

from fastapi.testclient import TestClient
from app.main import app


class PublicWebsiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_root_redirects_to_chinese_home(self) -> None:
        response = self.client.get("/", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/zh/")

    def test_chinese_home_renders_translated_content(self) -> None:
        response = self.client.get("/zh/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="zh"', response.text)
        self.assertIn("读真正推动你的信息。", response.text)
        self.assertIn("English", response.text)
        self.assertIn('href="/zh/invite/"', response.text)
        self.assertIn('href="/zh/feishu-guide/"', response.text)
        self.assertIn('href="/zh/login/"', response.text)
        self.assertIn('class="menu-toggle"', response.text)
        self.assertIn('aria-controls="primary-navigation"', response.text)
        self.assertIn('href="/zh/#how-it-works"', response.text)
        self.assertIn('href="/zh/#topics"', response.text)
        self.assertNotIn('aria-disabled="true"', response.text)

    def test_chinese_typography_uses_cjk_font_and_readable_rhythm(self) -> None:
        stylesheet = Path(__file__).parents[1] / "app" / "static" / "styles" / "site.css"
        css = stylesheet.read_text(encoding="utf-8")

        self.assertIn('"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei"', css)
        self.assertIn("html:lang(zh) .hero h1", css)
        self.assertIn("line-height: 1.18", css)
        self.assertIn("line-height: 1.8", css)
        self.assertIn("html:lang(zh) .topic-card p", css)

    def test_english_home_renders_translated_content(self) -> None:
        response = self.client.get("/en/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="en"', response.text)
        self.assertIn("Read what moves you.", response.text)
        self.assertIn("中文", response.text)
        self.assertIn('href="/en/invite/"', response.text)
        self.assertIn('href="/en/login/"', response.text)

    def test_authenticated_administrator_sees_dashboard_and_admin_links(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        app.state.settings = Settings("sqlite", "session-secret", "lookup-key", "webhook-key", admin_usernames="operator")
        app.state.session_factory = factory
        session = factory()
        try:
            user = User(username="operator", normalized_username="operator", password_hash=hash_password("a secure password"), recovery_code_hash=hash_password("another secure password"))
            session.add(user)
            session.flush()
            token = "homepage-session-token"
            session.add(AuthSession(user_id=user.id, token_hash=hash_opaque_token(token), expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
            session.commit()
            self.client.cookies.set("newsday_session", token)
            response = self.client.get("/zh/")
            self.assertIn('href="/zh/dashboard/"', response.text)
            self.assertIn('href="/zh/admin/"', response.text)
            self.assertNotIn('href="/zh/login/"', response.text)
        finally:
            session.close()
            del app.state.settings
            del app.state.session_factory

    def test_unknown_locale_redirects_to_chinese_home(self) -> None:
        response = self.client.get("/fr/", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/zh/")

    def test_feishu_guide_is_public_and_bilingual(self) -> None:
        chinese = self.client.get("/zh/feishu-guide/")
        english = self.client.get("/en/feishu-guide/")
        self.assertEqual(chinese.status_code, 200)
        self.assertIn("接入飞书群机器人", chinese.text)
        self.assertEqual(english.status_code, 200)
        self.assertIn("Connect a Feishu group bot", english.text)

    def test_healthz_is_available_without_external_services(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readyz_reports_configuration_and_database_readiness(self) -> None:
        unavailable = self.client.get("/readyz")
        self.assertEqual(unavailable.status_code, 503)

        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        app.state.settings = Settings("sqlite", "session-secret", "lookup-key", "webhook-key")
        app.state.session_factory = sessionmaker(bind=engine)
        try:
            ready = self.client.get("/readyz")
            self.assertEqual(ready.status_code, 200)
            self.assertEqual(ready.json(), {"status": "ready"})
        finally:
            del app.state.settings
            del app.state.session_factory


if __name__ == "__main__":
    unittest.main()
