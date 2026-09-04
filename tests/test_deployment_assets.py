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
            ("news-backup.timer", "news-backup.service"),
        ):
            self.assertIn(f"Unit={service_name}", (units / timer_name).read_text())
            self.assertTrue((units / service_name).is_file())

    def test_deploy_document_includes_readiness_and_migration(self):
        document = (ROOT / "DEPLOY.md").read_text()
        self.assertIn("alembic upgrade head", document)
        self.assertIn("/readyz", document)
        self.assertIn("pg_restore", document)

    def test_systemd_services_keep_filesystem_and_privilege_boundaries(self):
        units = ROOT / "ops" / "systemd"
        for service in units.glob("*.service"):
            content = service.read_text()
            self.assertIn("User=newsdigest", content)
            self.assertIn("EnvironmentFile=/etc/newsday/newsday.env", content)
            self.assertIn("NoNewPrivileges=true", content)
            self.assertIn("ProtectSystem=full", content)

    def test_nginx_templates_keep_tls_and_bootstrap_paths_separate(self):
        nginx = ROOT / "ops" / "nginx"
        final = (nginx / "newsday.conf").read_text()
        bootstrap = (nginx / "newsday-bootstrap.conf").read_text()
        holding = (nginx / "newsday-holding.conf").read_text()
        for directive in (
            "listen 443 ssl http2",
            "ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem",
            "client_max_body_size 1m",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-Forwarded-Proto",
        ):
            self.assertIn(directive, final)
        self.assertIn("/.well-known/acme-challenge/", bootstrap)
        self.assertNotIn("listen 443", bootstrap)
        self.assertIn("return 503", holding)
        self.assertIn("127.0.0.1:18000", final)


if __name__ == "__main__":
    unittest.main()
