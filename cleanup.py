"""清理超过保留期的日报产物。

默认仅预演；传入 ``--apply`` 才会删除。清理范围严格限定为：
``output/YYYY-MM-DD.md``、旧版 ``output/YYYY-MM-DD-llm.md``、
``output/YYYY-MM-DD.selected.json`` 和 ``data/raw/YYYY-MM-DD.json``。
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


DEFAULT_RETENTION_DAYS = 7
ARTIFACT_PATTERNS = (
    (Path("output"), re.compile(r"(\d{4}-\d{2}-\d{2})(?:-llm)?\.md")),
    (Path("output"), re.compile(r"(\d{4}-\d{2}-\d{2})\.selected\.json")),
    (Path("data/raw"), re.compile(r"(\d{4}-\d{2}-\d{2})\.json")),
)


@dataclass(frozen=True)
class Artifact:
    path: Path
    report_date: date
    size: int


def find_expired(
    root: Path,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    today: date | None = None,
) -> tuple[date, list[Artifact]]:
    """返回保留起始日期及其之前的日报产物。"""
    if retention_days < 1:
        raise ValueError("retention_days 必须大于等于 1")

    root = root.resolve()
    current_date = today or date.today()
    keep_from = current_date - timedelta(days=retention_days - 1)
    expired: list[Artifact] = []

    for relative_dir, pattern in ARTIFACT_PATTERNS:
        directory = root / relative_dir
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            match = pattern.fullmatch(path.name)
            if not match or not (path.is_file() or path.is_symlink()):
                continue
            try:
                report_date = date.fromisoformat(match.group(1))
            except ValueError:
                continue
            if report_date < keep_from:
                expired.append(
                    Artifact(path=path, report_date=report_date, size=path.lstat().st_size)
                )

    expired.sort(key=lambda item: (item.report_date, str(item.path)))
    return keep_from, expired


def remove_artifacts(artifacts: list[Artifact]) -> tuple[int, int]:
    """删除已确认的产物，返回删除数量和字节数。"""
    removed = 0
    released = 0
    for artifact in artifacts:
        artifact.path.unlink()
        removed += 1
        released += artifact.size
    return removed, released


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须大于等于 1")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="清理超过保留期的日报产物")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="项目根目录（默认是当前脚本所在目录）",
    )
    parser.add_argument(
        "--retention-days",
        type=positive_int,
        default=DEFAULT_RETENTION_DAYS,
        help="保留最近多少个自然日（默认 7）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际删除；省略时只预演",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    keep_from, artifacts = find_expired(root, args.retention_days)
    mode = "执行" if args.apply else "预演"
    print(
        f"[cleanup] 模式: {mode} ｜ 保留 {args.retention_days} 天 "
        f"｜ 保留起始日期: {keep_from.isoformat()}"
    )
    for artifact in artifacts:
        print(f"[cleanup] {'删除' if args.apply else '待删除'}: {artifact.path.relative_to(root)}")

    if args.apply:
        count, released = remove_artifacts(artifacts)
        print(f"[cleanup] 完成: 删除 {count} 个文件，释放 {released} 字节")
    else:
        released = sum(item.size for item in artifacts)
        print(f"[cleanup] 预演完成: {len(artifacts)} 个文件，共 {released} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
