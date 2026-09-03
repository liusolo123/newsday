"""Focused checks for public web routing and bilingual rendering."""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings

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

    def test_english_home_renders_translated_content(self) -> None:
        response = self.client.get("/en/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="en"', response.text)
        self.assertIn("Read what moves you.", response.text)
        self.assertIn("中文", response.text)

    def test_unknown_locale_redirects_to_chinese_home(self) -> None:
        response = self.client.get("/fr/", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/zh/")

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
