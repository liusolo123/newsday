"""build_report.py - 纯脚本模板组装每日早报 + 配比/字数/问号/来源校验
不经过任何 LLM:简述直出抓取字段,仅做清洗截断。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).parent
TODAY = date.today().isoformat()
RAW = ROOT / "data" / "raw" / f"{TODAY}.json"
OUT_DIR = ROOT / "output"
WPM = 500  # 字/分钟阅读速度

SOURCE_LABEL = {
    "github_trending": "GitHub Trending",
    "github_search": "GitHub 搜索",
    "hacker_news": "Hacker News",
    "lobste_rs": "Lobste.rs",
    "weibo_hot": "微博热搜",
    "google_news": "Google News 财经",
    "wallstreetcn": "华尔街见闻",
    "eastmoney_724": "东方财富 7x24",
    "marketwatch": "MarketWatch",
}

# 目标配比(20 条新闻基准;热搜为 Top10 话题清单,不计入新闻条数)
TARGET = {"github": 5, "tech": 6, "finance": 9, "hot": 10}


def fix_title(t: str) -> str:
    """标题清洗:合并换行/空白,零问号。"""
    t = re.sub(r"\s+", " ", t).strip()
    if "?" in t or "？" in t:
        t = t.replace("?", "").replace("？", "")
        t = t.rstrip("。.!！ ") + "。"
    return t.strip()


def clean_summary(s: str) -> str:
    """简述:取首个不含问号的完整句(≤140 字);无完整句则截断并去问号。"""
    if not s or not s.strip():
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    for end in ("。", "！", "!"):
        idx = s.find(end)
        if 0 < idx <= 140 and "?" not in s[: idx + 1] and "？" not in s[: idx + 1]:
            return s[: idx + 1]
    cut = s[:140].split("。")[0]
    cut = re.split(r"[?？]", cut)[0]  # 问号及其后内容一律丢弃
    cut = cut.rstrip("?？")
    return cut if cut else ""


def pick(items: list[dict], n: int) -> list[dict]:
    """按 score 降序去重挑选,标题去重。"""
    seen, out = set(), []
    for it in sorted(items, key=lambda x: -x.get("score", 0)):
        t = it["title"]
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(it)
        if len(out) >= n:
            break
    return out


def pick_balanced(items: list[dict], n: int, min_zh: int = 2) -> list[dict]:
    """按题材分组轮转选条(每组取分数最高者,同源最多 1 条,保证题材与语种均衡)。"""
    from collections import defaultdict
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for it in sorted(items, key=lambda x: -x.get("score", 0)):
        by_topic[it.get("topic", "其他")].append(it)
    topics = list(by_topic.keys())
    picked: list[dict] = []
    seen_title: set[str] = set()
    seen_source: set[str] = set()
    while len(picked) < n:
        advanced = False
        for t in topics:
            pool = by_topic[t]
            # 跳过已选标题/已选来源的条目
            while pool and (pool[0]["title"] in seen_title
                            or pool[0]["source"] in seen_source):
                pool.pop(0)
            if pool:
                it = pool.pop(0)
                seen_title.add(it["title"])
                seen_source.add(it["source"])
                picked.append(it)
                advanced = True
                if len(picked) >= n:
                    break
        if not advanced:
            break
    # 中文配额:不足 min_zh 时,用中文池高分条目替换已选中分数最低的非中文条目
    zh_cnt = sum(1 for it in picked if it.get("lang") == "zh")
    if zh_cnt < min_zh:
        zh_pool = sorted(
            [it for it in items if it.get("lang") == "zh"
             and it["title"] not in seen_title and it["source"] not in seen_source],
            key=lambda x: -x.get("score", 0))
        for it in zh_pool:
            if zh_cnt >= min_zh:
                break
            candidates = [p for p in picked if p.get("lang") != "zh"]
            if not candidates:
                break
            weakest = min(candidates, key=lambda p: p.get("score", 0))
            picked.remove(weakest)
            seen_title.discard(weakest["title"])
            seen_source.discard(weakest["source"])
            picked.append(it)
            seen_title.add(it["title"])
            seen_source.add(it["source"])
            zh_cnt += 1
    return picked


def render(items: list[dict]) -> list[str]:
    if not items:
        return ["（今日该板块数据源暂未获取到）"]
    lines = []
    for i, it in enumerate(items, 1):
        title = fix_title(it["title"])
        s = clean_summary(it.get("summary", ""))
        if not s:
            s = it.get("extra", "") or "详情暂未获取到"
        src = SOURCE_LABEL.get(it["source"], it["source"])
        lines.append(f"{i}. **{title}** — {s}（来源：{src}）")
    return lines


def render_hot(items: list[dict]) -> list[str]:
    """热搜板块:纯话题关键词清单,不润色不带简述。"""
    if not items:
        return ["（今日微博热搜暂未获取到）"]
    return [f"{i}. {fix_title(it['title'])}" for i, it in enumerate(items, 1)]


def count_cn(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def main() -> int:
    data = json.loads(RAW.read_text(encoding="utf-8"))
    all_items = [it for s in data["sources"].values() for it in s.get("items", [])]
    by_bucket = {"github": [], "tech": [], "finance": [], "hot": []}
    for it in all_items:
        b = it.get("bucket")
        if b in by_bucket:
            by_bucket[b].append(it)

    sections = [
        ("一、科技 · GitHub 热门项目", pick(by_bucket["github"], TARGET["github"])),
        ("二、科技 · AI / 半导体 / 开源 / 消费电子", pick_balanced(by_bucket["tech"], TARGET["tech"], min_zh=4)),
        ("三、财经(宏观 → 政策 → 行情 → 公司)", pick(by_bucket["finance"], TARGET["finance"])),
        ("四、微博热搜", pick(by_bucket["hot"], TARGET["hot"])),
    ]

    md = [f"# 每日新闻早报 · {TODAY}", ""]
    body_blocks = []
    for name, items in sections:
        if name.startswith("四、"):
            block = (f"## {name}" + "\n\n" + "\n".join(render_hot(items)))
        else:
            block = f"## {name}（{len(items)} 条）" + "\n\n" + "\n".join(render(items))
        body_blocks.append(block)
    body = "\n\n".join(body_blocks)
    total_cn = count_cn(body)
    minutes = max(1, round(total_cn / WPM))
    news_n = sum(len(items) for name, items in sections if not name.startswith("四、"))
    hot_n = sum(len(items) for name, items in sections if name.startswith("四、"))
    md.append(f"预计阅读时长：约 {minutes} 分钟 ｜ 新闻 {news_n} 条 ｜ 微博热搜 Top{hot_n}")
    md.append(f"> 模板版：纯脚本自动组装，简述为抓取原文，未做 LLM 润色。")
    md.append("")
    md.append(body)
    md.append("")
    md.append("> 说明：来源被墙/无正文时注明「详情暂未获取到」；数据全部来自当日原始接口直抓。")
    text = "\n".join(md)

    # ---- 校验 ----
    counts = {name: len(items) for name, items in sections}
    empty_sections = {name for name, items in sections if not items}
    hints = []
    for name in empty_sections:
        short = name.split("·")[0].split("(")[0]
        hints.append(f"提示:{short}数据源今日暂未获取到,该板块缺额已注明")
    issues = []
    for label, (sec_keys, want) in {
        "科技": (["一、科技 · GitHub 热门项目", "二、科技 · AI / 半导体 / 开源 / 消费电子"], TARGET["github"] + TARGET["tech"]),
        "GitHub占科技40%": (["一、科技 · GitHub 热门项目"], TARGET["github"]),
        "财经": (["三、财经(宏观 → 政策 → 行情 → 公司)"], TARGET["finance"]),
        "热搜": (["四、微博热搜"], TARGET["hot"]),
    }.items():
        if all(k in empty_sections for k in sec_keys):
            continue  # 对应源不可用,允许缺口并已注明
        got = sum(counts[k] for k in sec_keys)
        if abs(got - want) > 1:
            issues.append(f"配比[{label}]:实际 {got},目标 {want}")

    if total_cn > 5000:
        issues.append(f"字数超标:{total_cn} > 5000")
    for q in ("?", "？"):
        for ln in text.splitlines():
            if q in ln and not ln.startswith("#") and "暂无" not in ln:
                issues.append("问号违规: " + ln[:50])
    for ln in text.splitlines():
        # 仅检查"条目行"(数字+.**开头)是否缺来源,避免标题自身含 ** 导致的误报
        if re.match(r"^\d+\. \*\*", ln) and "（来源：" not in ln:
            issues.append("缺来源标注: " + ln[:50])

    print("=" * 50)
    print(f"早报生成 -> {OUT_DIR / f'{TODAY}.md'}")
    print(f"配比: GitHub {counts[sections[0][0]]} / 科技合计 {counts[sections[0][0]]+counts[sections[1][0]]} / 财经 {counts[sections[2][0]]} / 热搜Top {counts[sections[3][0]]} / 新闻总条数 {news_n}")
    print(f"总字数(中文): {total_cn} ｜ 预计阅读: {minutes} 分钟")
    if issues:
        print("!! 校验未通过:")
        for i in issues:
            print("   -", i)
    else:
        print("校验通过: 配比/字数/问号/来源 全部 OK")
    if hints:
        print("注意:")
        for h in hints:
            print("   -", h)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{TODAY}.md").write_text(text, encoding="utf-8")

    # 输出选中条目清单,供 llm_polish.py 逐条润色
    selected = {
        "generated_at": TODAY,
        "sections": [
            {"name": name, "items": [
                {k: it.get(k) for k in
                 ("title", "summary", "url", "source", "bucket", "topic", "lang", "score", "extra", "published_at")}
                for it in items]}
            for name, items in sections
        ],
    }
    (OUT_DIR / f"{TODAY}.selected.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
