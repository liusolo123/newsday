"""以可告警、可维护的方式运行每日新闻任务。"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ops_maintenance import send_alert

ROOT = Path(__file__).parent
STEPS = (
    ("fetch_sources.py",),
    ("build_report.py",),
    ("llm_polish.py",),
    ("send_feishu.py",),
    ("cleanup.py", "--apply"),
)


def alert_failure(step: str, return_code: int) -> None:
    message = (
        "每日新闻任务失败\n"
        f"时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"步骤：{step}\n退出码：{return_code}\n"
        "请查看 /root/newsdigest/run.log。"
    )
    try:
        send_alert(message)
        print(f"[daily] 已发送失败告警：{step}")
    except Exception as exc:
        print(f"[daily] 发送失败告警失败：{exc}")


def main() -> int:
    for command in STEPS:
        step = command[0]
        result = subprocess.run([sys.executable, *command], cwd=ROOT, check=False)
        if result.returncode:
            alert_failure(step, result.returncode)
            return result.returncode
    result = subprocess.run([sys.executable, "ops_maintenance.py", "--daily"], cwd=ROOT, check=False)
    if result.returncode:
        alert_failure("ops_maintenance.py", result.returncode)
        return result.returncode
    print("[daily] 每日任务全部完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
