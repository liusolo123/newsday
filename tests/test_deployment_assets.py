"""Minimal consistency checks for production deployment assets."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentAssetTests(unittest.TestCase):
    def test_systemd_timers_reference_existing_services(self):
        units = ROOT / "ops" / "systemd"
        for timer_name, service_name in (
            ("news-schedule.timer", "news-schedule.service"),
            ("news-dispatch.timer", "news-dispatch.service"),
            ("news-ingest.timer", "news-ingest.service"),
            ("news-retention.timer", "news-retention.service"),
        ):
            self.assertIn(f"Unit={service_name}", (units / timer_name).read_text())
            self.assertTrue((units / service_name).is_file())

    def test_deploy_document_includes_readiness_and_migration(self):
        document = (ROOT / "DEPLOY.md").read_text()
        self.assertIn("alembic upgrade head", document)
        self.assertIn("/readyz", document)


if __name__ == "__main__":
    unittest.main()
