"""日报任务的告警、备份和日志维护。"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).parent
LOG_FILE = ROOT / "run.log"
BACKUP_DIR = ROOT / "backups"
LOG_BACKUP_DIR = BACKUP_DIR / "logs"
DB_FILE = ROOT / "data" / "finnews.db"
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


def backup_database() -> Path | None:
    if not DB_FILE.exists():
        print("[ops] 数据库不存在，跳过备份")
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    raw_copy = BACKUP_DIR / f".finnews-{today}.db.tmp"
    compressed_tmp = BACKUP_DIR / f".finnews-{today}.db.gz.tmp"
    target = BACKUP_DIR / f"finnews-{today}.db.gz"
    try:
        with sqlite3.connect(DB_FILE) as source, sqlite3.connect(raw_copy) as destination:
            source.backup(destination)
        with raw_copy.open("rb") as source, gzip.open(compressed_tmp, "wb") as destination:
            shutil.copyfileobj(source, destination)
        compressed_tmp.replace(target)
    finally:
        raw_copy.unlink(missing_ok=True)
        compressed_tmp.unlink(missing_ok=True)
    removed = _prune(BACKUP_DIR, "finnews-*.db.gz", BACKUP_RETENTION_DAYS)
    print(f"[ops] 数据库备份 -> {target.name}；清理旧备份 {removed} 个")
    return target


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
