from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from cleanup import find_expired, remove_artifacts


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        (self.root / "output").mkdir()
        (self.root / "data/raw").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def create(self, relative_path: str, content: str = "x") -> Path:
        path = self.root / relative_path
        path.write_text(content, encoding="utf-8")
        return path

    def test_keeps_seven_dates_and_only_selects_supported_artifacts(self) -> None:
        expired_paths = {
            self.create("output/2026-09-03.md"),
            self.create("output/2026-09-03-llm.md"),
            self.create("output/2026-09-03.selected.json"),
            self.create("data/raw/2026-09-03.json"),
        }
        retained_paths = {
            self.create("output/2026-09-04.md"),
            self.create("output/2026-09-10.selected.json"),
            self.create("data/raw/2026-09-10.json"),
            self.create("output/2026-09-03.notes.txt"),
            self.create("data/raw/not-a-date.json"),
        }

        keep_from, artifacts = find_expired(
            self.root, retention_days=7, today=date(2026, 9, 10)
        )

        self.assertEqual(keep_from, date(2026, 9, 4))
        self.assertEqual({item.path for item in artifacts}, expired_paths)
        self.assertTrue(all(path.exists() for path in expired_paths | retained_paths))

    def test_remove_deletes_only_confirmed_artifacts(self) -> None:
        old = self.create("output/2026-09-01.md", "old")
        recent = self.create("output/2026-09-10.md", "recent")
        _, artifacts = find_expired(
            self.root, retention_days=7, today=date(2026, 9, 10)
        )

        count, released = remove_artifacts(artifacts)

        self.assertEqual(count, 1)
        self.assertEqual(released, 3)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_rejects_invalid_retention(self) -> None:
        with self.assertRaises(ValueError):
            find_expired(self.root, retention_days=0, today=date(2026, 9, 10))


if __name__ == "__main__":
    unittest.main()
