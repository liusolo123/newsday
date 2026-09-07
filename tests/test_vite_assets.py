"""Checks for FastAPI/Jinja integration with Vite assets."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.config import Settings
from app.services.vite_assets import ViteAssetError, vite_assets


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "sqlite",
        "app_session_secret": "session-secret",
        "invite_lookup_key": "lookup-key",
        "webhook_encryption_key": "webhook-key",
        "environment": "development",
    }
    values.update(overrides)
    return Settings(**values)


class ViteAssetTests(unittest.TestCase):
    def test_development_mode_uses_only_local_vite_urls(self) -> None:
        assets = vite_assets(_settings(frontend_dev_mode=True))

        self.assertTrue(assets.development)
        self.assertEqual(assets.dev_client, "http://127.0.0.1:5173/@vite/client")
        self.assertEqual(assets.entry_script, "http://127.0.0.1:5173/frontend/main.js")

    def test_development_mode_rejects_non_local_server(self) -> None:
        with self.assertRaises(ViteAssetError):
            vite_assets(_settings(frontend_dev_mode=True, vite_dev_server_url="https://example.com"))

    def test_production_mode_reads_hashed_manifest_assets(self) -> None:
        with TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "frontend/main.js": {
                            "file": "assets/main-123.js",
                            "css": ["assets/main-123.css"],
                            "imports": ["assets/vendor.js"],
                        },
                        "assets/vendor.js": {"file": "assets/vendor-456.js", "css": ["assets/vendor-456.css"]},
                    }
                ),
                encoding="utf-8",
            )
            with patch("app.services.vite_assets.MANIFEST_PATH", manifest):
                assets = vite_assets(_settings(environment="production"))

        self.assertFalse(assets.development)
        self.assertFalse(assets.legacy)
        self.assertEqual(assets.entry_script, "/static/dist/assets/main-123.js")
        self.assertEqual(assets.module_preloads, ("/static/dist/assets/vendor-456.js",))
        self.assertEqual(
            assets.stylesheets,
            ("/static/dist/assets/main-123.css", "/static/dist/assets/vendor-456.css"),
        )

    def test_production_mode_requires_a_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with patch("app.services.vite_assets.MANIFEST_PATH", missing):
                with self.assertRaisesRegex(ViteAssetError, "run npm run build"):
                    vite_assets(_settings(environment="production"))

    def test_production_mode_rejects_the_development_server(self) -> None:
        with self.assertRaisesRegex(ViteAssetError, "cannot be enabled"):
            vite_assets(_settings(environment="production", frontend_dev_mode=True))

    def test_development_without_a_build_keeps_legacy_styles_available(self) -> None:
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with patch("app.services.vite_assets.MANIFEST_PATH", missing):
                assets = vite_assets(_settings())

        self.assertTrue(assets.legacy)
        self.assertEqual(assets.stylesheets, ("/static/styles/site.css",))
