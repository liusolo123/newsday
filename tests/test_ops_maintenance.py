from __future__ import annotations

import gzip
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.modules.setdefault("requests", Mock())

import ops_maintenance


class OpsMaintenanceTests(unittest.TestCase):
    def test_backup_database_and_rotate_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "data" / "finnews.db"
            db_path.parent.mkdir()
            with sqlite3.connect(db_path) as database:
                database.execute("CREATE TABLE sample (value TEXT)")
                database.execute("INSERT INTO sample VALUES ('ok')")
            log_path = root / "run.log"
            log_path.write_text("daily log", encoding="utf-8")

            with patch.object(ops_maintenance, "DB_FILE", db_path), patch.object(ops_maintenance, "BACKUP_DIR", root / "backups"), patch.object(ops_maintenance, "LOG_BACKUP_DIR", root / "backups/logs"), patch.object(ops_maintenance, "LOG_FILE", log_path), patch.object(ops_maintenance, "LOG_ROTATE_BYTES", 1):
                backup = ops_maintenance.backup_database()
                archive = ops_maintenance.rotate_log()

            self.assertIsNotNone(backup)
            self.assertIsNotNone(archive)
            self.assertEqual(log_path.read_text(encoding="utf-8"), "")
            with gzip.open(archive, "rt", encoding="utf-8") as compressed:
                self.assertEqual(compressed.read(), "daily log")
            with gzip.open(backup, "rb") as compressed:
                restored = root / "restored.db"
                restored.write_bytes(compressed.read())
            with sqlite3.connect(restored) as database:
                self.assertEqual(database.execute("SELECT value FROM sample").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
