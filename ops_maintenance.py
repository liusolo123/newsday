"""日报任务的告警、备份和日志维护。"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import requests

from app.services.postgres_backup import backup_postgresql

ROOT = Path(__file__).parent
LOG_FILE = ROOT / "run.log"
BACKUP_DIR = ROOT / "backups"
LOG_BACKUP_DIR = BACKUP_DIR / "logs"
LOG_ROTATE_BYTES = 5 * 1024 * 1024
BACKUP_RETENTION_DAYS = 14


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("ALERT_FEISHU_WEBHOOK", "FEISHU_WEBHOOK", "DATABASE_URL", "POSTGRES_BACKUP_DIR"):
        if value := os.getenv(key):
            values[key] = value
    return values


def send_alert(message: str) -> bool:
    env = load_env()
    webhook = env.get("ALERT_FEISHU_WEBHOOK") or env.get("FEISHU_WEBHOOK")
    if not webhook:
        print("[ops] 未配置告警 Webhook，无法发送失败告警")
        return False
    response = requests.post(
        webhook,
        json={"msg_type": "text", "content": {"text": message}},
        timeout=15,
    )
    response.raise_for_status()
    if response.json().get("code") != 0:
        raise RuntimeError("飞书告警接口返回失败")
    return True


def _prune(directory: Path, pattern: str, retention_days: int) -> int:
    cutoff = datetime.now().timestamp() - timedelta(days=retention_days).total_seconds()
    removed = 0
    for item in directory.glob(pattern):
        if item.is_file() and item.stat().st_mtime < cutoff:
            item.unlink()
            removed += 1
    return removed


def backup_database() -> Path:
    """Compatibility entrypoint for legacy daily_job.py, now using pg_dump."""
    env = load_env()
    database_url = os.getenv("DATABASE_URL") or env.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL backups")
    backup_dir = Path(os.getenv("POSTGRES_BACKUP_DIR") or env.get("POSTGRES_BACKUP_DIR", str(BACKUP_DIR)))
    result = backup_postgresql(database_url, backup_dir, retention_days=BACKUP_RETENTION_DAYS)
    print(f"[ops] PostgreSQL backup -> {result.target.name}；清理旧备份 {result.removed} 个")
    return result.target


def rotate_log() -> Path | None:
    if not LOG_FILE.exists() or LOG_FILE.stat().st_size < LOG_ROTATE_BYTES:
        return None
    LOG_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = LOG_BACKUP_DIR / f"run-{datetime.now():%Y%m%d-%H%M%S}.log.gz"
    with LOG_FILE.open("rb") as source, gzip.open(target, "wb") as destination:
        shutil.copyfileobj(source, destination)
    with LOG_FILE.open("r+b") as current:
        current.truncate(0)
    removed = _prune(LOG_BACKUP_DIR, "run-*.log.gz", BACKUP_RETENTION_DAYS)
    print(f"[ops] 日志归档 -> {target.name}；清理旧归档 {removed} 个")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="执行日报运维维护")
    parser.add_argument("--daily", action="store_true", help="备份数据库并按阈值轮转日志")
    args = parser.parse_args()
    if not args.daily:
        parser.error("需要 --daily")
    backup_database()
    rotate_log()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
