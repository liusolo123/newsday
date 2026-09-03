"""tech_sources_test.py - 科技板块新增 RSS 源连通性与质量测试(独立脚本,不改生产代码)
用法: python tech_sources_test.py
每个源带候选 URL,依次尝试;统计可达性/条数/简述完整度/耗时。
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import feedparser
import requests

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# (名称, [候选 URL], 题材, 权威性权重)
SOURCES = [
    ("oschina", ["https://www.oschina.net/news/rss",
                 "https://www.oschina.net/feed"], "开源生态", 6),
    ("jiqizhixin", ["https://www.jiqizhixin.com/rss",
                    "https://www.qbitai.com/feed"], "AI", 7),
    ("36kr", ["https://36kr.com/feed"], "科技创投", 6),
    ("venturebeat", ["https://venturebeat.com/feed/"], "AI/半导体", 8),
    ("arstechnica", ["https://feeds.arstechnica.com/arstechnica/index",
                     "https://arstechnica.com/feed/"], "泛科技", 8),
    ("phoronix", ["https://www.phoronix.com/rss.php"], "开源/硬件", 7),
    ("theverge", ["https://www.theverge.com/rss/index.xml"], "消费电子", 8),
]


def test_one(name: str, urls: list[str], topic: str, weight: int) -> dict:
    t0 = time.time()
    used = ""
    for url in urls:
        try:
            r = requests.get(url, headers=UA, timeout=12)
            r.raise_for_status()
            d = feedparser.parse(r.content)
            entries = d.entries
            if not entries:
                continue
            used = url
            with_desc = sum(
                1 for e in entries
                if ((e.get("summary") or e.get("description") or "").strip()))
            sample = []
            for e in entries[:3]:
                title = (e.get("title") or "").strip()[:46]
                desc = ((e.get("summary") or e.get("description")) or "").strip()[:60]
                sample.append(f"    - {title}  |  {desc}")
            return {"name": name, "topic": topic, "weight": weight, "ok": True,
                    "n": len(entries), "with_desc": with_desc,
                    "cost": time.time() - t0, "url": used, "sample": sample}
        except Exception as exc:
            last_err = str(exc)[:100]
    return {"name": name, "topic": topic, "weight": weight, "ok": False,
            "err": last_err, "cost": time.time() - t0, "sample": []}


def main() -> int:
    print(f"科技板块新增 RSS 源测试 ｜ 本地网络 ｜ {time.strftime('%Y-%m-%d %H:%M')}\n")
    results = [test_one(*s) for s in SOURCES]
    print(f"{'源':<13}{'题材':<11}{'状态':<6}{'条数':<6}{'有简述':<8}{'耗时':<6}")
    print("-" * 58)
    for r in results:
        if r["ok"]:
            print(f"{r['name']:<13}{r['topic']:<11}OK    {r['n']:<6}{r['with_desc']:<8}{r['cost']:.1f}s")
        else:
            print(f"{r['name']:<13}{r['topic']:<11}FAIL  {'-':<6}{'-':<8}{r['cost']:.1f}s  {r['err']}")
    print()
    for r in results:
        if r["ok"] and r["sample"]:
            print(f"== {r['name']} ({r['topic']}) 样例 ==")
            for s in r["sample"]:
                print(s)
            print()
    ok_n = sum(1 for r in results if r["ok"])
    print(f"汇总: {ok_n}/{len(results)} 个源可用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
