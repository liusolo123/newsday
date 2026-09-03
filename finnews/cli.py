"""CLI entry: python -m finnews fetch|view|init-schedule"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import run_pipeline
from .storage import Storage

DEFAULT_CONFIG = Path("config.json")
DEFAULT_DB = Path("data/finnews.db")
DEFAULT_REPORT = Path("data/latest.json")


def _print_report(report: dict):
    stats = report["stats"]
    print(f"[finnews] fetched={stats['total_fetched']} new={stats['new_stored']} "
          f"hits={stats['keyword_hits']} macro={stats['macro']} micro={stats['micro']}")
    if stats.get("source_failures"):
        for f in stats["source_failures"]:
            print(f"  ! source failed: {f}")
    print()
    for section, label in (
        ("keyword_hits", "关键词命中"),
        ("macro_top", "宏观精选"),
        ("micro_top", "微观精选"),
    ):
        items = report[section]
        print(f"== {label} ({len(items)}) ==")
        for it in items:
            print(f"  [{it['importance']}] {it['title']}")
            if it.get("summary"):
                print(f"      {it['summary'][:90]}")
        print()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="finnews", description="财经新闻聚合")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="抓取、去重、筛选并生成报告")
    p_fetch.add_argument("--report", default=str(DEFAULT_REPORT), help="报告 JSON 输出路径")

    p_view = sub.add_parser("view", help="查看最近入库的新闻")
    p_view.add_argument("--limit", type=int, default=30)

    args = parser.parse_args(argv)

    if args.cmd == "fetch":
        report = run_pipeline(args.config, args.db, args.report)
        _print_report(report)
    elif args.cmd == "view":
        storage = Storage(args.db)
        try:
            rows = storage.recent(args.limit)
        finally:
            storage.close()
        if not rows:
            print("数据库为空，请先运行 fetch")
        for r in rows:
            print(f"[{r['score']}][{'命中' if r['is_keyword_hit'] else r['bucket'] or '其他'}] "
                  f"({r['source']}) {r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
