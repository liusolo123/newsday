"""Run a PostgreSQL backup from a protected systemd environment file."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.config import Settings
from app.services.postgres_backup import backup_postgresql


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and retain PostgreSQL backups")
    parser.add_argument("--apply", action="store_true", help="write a backup (default is dry-run)")
    parser.add_argument("--backup-dir", type=Path, default=Path(os.getenv("POSTGRES_BACKUP_DIR", "/var/lib/newsday/backups/postgresql")))
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--pg-dump-path", default=os.getenv("PG_DUMP_PATH", "pg_dump"))
    args = parser.parse_args()
    settings = Settings.from_environment()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    try:
        result = backup_postgresql(
            settings.database_url,
            args.backup_dir,
            retention_days=args.retention_days,
            pg_dump_path=args.pg_dump_path,
            dry_run=not args.apply,
        )
    except Exception as error:
        try:
            from ops_maintenance import send_alert

            send_alert(f"[backup] failed: {type(error).__name__}")
        except Exception:
            pass
        raise
    action = "would create" if result.dry_run else "created"
    print(f"[backup] {action} {result.target.name}; pruned {result.removed} old backup(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
