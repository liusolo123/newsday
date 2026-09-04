"""Safe, file-based PostgreSQL backups for the production deployment."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class BackupResult:
    """The non-sensitive result of one backup attempt."""

    target: Path
    removed: int
    dry_run: bool


def _connection_environment(database_url: str) -> dict[str, str]:
    parsed = urlsplit(database_url)
    if parsed.scheme.split("+", 1)[0] not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use a PostgreSQL dialect")
    if not parsed.hostname or not parsed.path.lstrip("/"):
        raise ValueError("DATABASE_URL must include a PostgreSQL host and database name")

    environment = os.environ.copy()
    environment["PGHOST"] = parsed.hostname
    environment["PGPORT"] = str(parsed.port or 5432)
    environment["PGDATABASE"] = unquote(parsed.path.lstrip("/"))
    if parsed.username:
        environment["PGUSER"] = unquote(parsed.username)
    if parsed.password is not None:
        environment["PGPASSWORD"] = unquote(parsed.password)
    return environment


def _prune(directory: Path, retention_days: int, now: datetime) -> int:
    cutoff = now - timedelta(days=retention_days)
    removed = 0
    for item in directory.glob("newsday-*.dump"):
        if item.is_file() and datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc) < cutoff:
            item.unlink()
            removed += 1
    return removed


def backup_postgresql(
    database_url: str,
    backup_dir: Path,
    *,
    retention_days: int = 14,
    pg_dump_path: str = "pg_dump",
    now: datetime | None = None,
    dry_run: bool = False,
) -> BackupResult:
    """Create a PostgreSQL custom-format dump and prune old completed dumps.

    The URL is translated into libpq environment variables so credentials are
    never placed in the command line or printed by this module.
    """
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    connection_environment = _connection_environment(database_url)
    timestamp = now or datetime.now(timezone.utc)
    target = backup_dir / f"newsday-{timestamp:%Y%m%dT%H%M%SZ}.dump"
    temporary = target.with_suffix(".dump.tmp")
    if dry_run:
        return BackupResult(target=target, removed=0, dry_run=True)

    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    try:
        subprocess.run(
            [
                pg_dump_path,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(temporary),
            ],
            check=True,
            env=connection_environment,
        )
        temporary.chmod(0o600)
        temporary.replace(target)
        removed = _prune(backup_dir, retention_days, timestamp)
    finally:
        temporary.unlink(missing_ok=True)
    return BackupResult(target=target, removed=removed, dry_run=False)
