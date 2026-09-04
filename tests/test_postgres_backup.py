"""Tests for PostgreSQL backup safety and retention behavior."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.services.postgres_backup import backup_postgresql


DATABASE_URL = "postgresql+psycopg://news%20user:secret%20value@db.example:5433/news%20db"


class PostgreSQLBackupTests(unittest.TestCase):
    def test_backup_uses_libpq_environment_and_prunes_expired_files(self) -> None:
        now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            backup_dir = Path(directory) / "backups"
            backup_dir.mkdir()
            old = backup_dir / "newsday-20260801T000000Z.dump"
            old.write_text("old", encoding="utf-8")
            old_timestamp = (now - timedelta(days=15)).timestamp()
            os.utime(old, (old_timestamp, old_timestamp))

            def fake_dump(command, *, check, env):
                self.assertTrue(check)
                self.assertNotIn(DATABASE_URL, command)
                self.assertEqual(env["PGHOST"], "db.example")
                self.assertEqual(env["PGPORT"], "5433")
                self.assertEqual(env["PGDATABASE"], "news db")
                self.assertEqual(env["PGUSER"], "news user")
                self.assertEqual(env["PGPASSWORD"], "secret value")
                Path(command[-1]).write_bytes(b"backup")

            with patch("app.services.postgres_backup.subprocess.run", side_effect=fake_dump):
                result = backup_postgresql(DATABASE_URL, backup_dir, now=now)

            self.assertTrue(result.target.is_file())
            self.assertEqual(result.target.read_bytes(), b"backup")
            self.assertEqual(result.target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result.removed, 1)
            self.assertFalse(old.exists())

    def test_backup_rejects_non_postgresql_url_and_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backup_dir = Path(directory) / "backups"
            with self.assertRaisesRegex(ValueError, "PostgreSQL"):
                backup_postgresql("sqlite:///local.db", backup_dir)
            result = backup_postgresql(DATABASE_URL, backup_dir, dry_run=True)
            self.assertTrue(result.dry_run)
            self.assertFalse(backup_dir.exists())


if __name__ == "__main__":
    unittest.main()
