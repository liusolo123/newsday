from __future__ import annotations

import gzip
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
            log_path = root / "run.log"
            log_path.write_text("daily log", encoding="utf-8")
            target = root / "backups" / "newsday-20260904T000000Z.dump"

            with patch.dict("os.environ", {"DATABASE_URL": "postgresql://user:password@localhost/newsday"}, clear=True), patch.object(ops_maintenance, "BACKUP_DIR", root / "backups"), patch.object(ops_maintenance, "LOG_BACKUP_DIR", root / "backups/logs"), patch.object(ops_maintenance, "LOG_FILE", log_path), patch.object(ops_maintenance, "LOG_ROTATE_BYTES", 1), patch.object(ops_maintenance, "backup_postgresql", return_value=Mock(target=target, removed=0)) as backup_postgresql:
                backup = ops_maintenance.backup_database()
                archive = ops_maintenance.rotate_log()

            self.assertEqual(backup, target)
            backup_postgresql.assert_called_once()
            self.assertIsNotNone(archive)
            self.assertEqual(log_path.read_text(encoding="utf-8"), "")
            with gzip.open(archive, "rt", encoding="utf-8") as compressed:
                self.assertEqual(compressed.read(), "daily log")


if __name__ == "__main__":
    unittest.main()
