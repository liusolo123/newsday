"""Checks for the isolated no-PostgreSQL local development fallback."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy import inspect

from app.config import Settings
from app.db import build_engine
from app.dev_database_cli import ensure_development_database


class DevelopmentDatabaseTests(unittest.TestCase):
    def test_creates_the_local_sqlite_schema(self) -> None:
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "newsday-dev.db"
            settings = Settings(
                database_url=f"sqlite+pysqlite:///{database_path}",
                app_session_secret="session-secret",
                invite_lookup_key="lookup-key",
                webhook_encryption_key="webhook-key",
            )
            ensure_development_database(settings)
            engine = build_engine(settings.database_url)
            try:
                self.assertIn("public_news_batches", inspect(engine).get_table_names())
            finally:
                engine.dispose()

    def test_rejects_production_and_non_sqlite_databases(self) -> None:
        production = Settings("sqlite", "session", "lookup", "webhook", environment="production")
        postgres = Settings("postgresql+psycopg://localhost/newsday", "session", "lookup", "webhook")

        with self.assertRaisesRegex(RuntimeError, "disabled in production"):
            ensure_development_database(production)
        with self.assertRaisesRegex(RuntimeError, "requires a SQLite"):
            ensure_development_database(postgres)
