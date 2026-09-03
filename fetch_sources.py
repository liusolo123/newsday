"""fetch_sources.py - 每日新闻早报 · 统一抓取入口
科技(GitHub Trending/Search、Hacker News、Lobste.rs) + 微博热搜 + 财经(finnews 复用)
原则:全部直连原始页面/接口,不经过任何 LLM;源失败 -> unavailable 标记。
"""
from __future__ import annotations

import json
import re
import sys
import time
import datetime as dt
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "data" / "raw"
TIMEOUT = 10  # 单请求超时(秒),快速失败不拖慢整体
TRENDING_TIMEOUT = 20  # github.com 网页端在国内较慢,单独放宽

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def clean_text(s: str, limit: int = 150) -> str:
    if not s:
        return ""
    s = BeautifulSoup(s, "html.parser").get_text(" ", strip=True)
    s = re.sub(r"\s+", " ", s)
    return s[:limit]


def first_sentence(s: str, limit: int = 120) -> str:
    """简述清洗:取首个完整句,超长截断。空则返回空串。"""
    if not s:
        return ""
    s = clean_text(s, limit=400)
    for end in ("。", "！", "!", ".", "…"):
        idx = s.find(end)
        if 0 < idx <= limit:
            return s[: idx + 1]
    return s[:limit]


# ---------------- 科技源 ----------------

def fetch_github_trending() -> list[dict]:
    r = requests.get("https://github.com/trending?since=daily", headers=UA, timeout=TRENDING_TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for art in soup.select("article.Box-row"):
        h2 = art.select_one("h2 a")
        if not h2:
            continue
        repo = h2.get_text(" ", strip=True).replace(" ", "")
        desc_el = art.select_one("p")
        lang_el = art.select_one('[itemprop="programmingLanguage"]')
        items.append({
            "title": repo,
            "summary": desc_el.get_text(strip=True) if desc_el else "",
            "url": f"https://github.com/{repo}",
            "source": "github_trending",
            "bucket": "github",
            "score": 10,
            "extra": lang_el.get_text(strip=True) if lang_el else "",
        })
    return items


def fetch_github_search() -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    url = (f"https://api.github.com/search/repositories?q=created:>{since}"
           f"&sort=stars&order=desc&per_page=20")
    r = requests.get(url, headers={**UA, "Accept": "application/vnd.github+json"}, timeout=TIMEOUT)
    r.raise_for_status()
    items = []
    for it in r.json().get("items", []):
        items.append({
            "title": it.get("full_name", ""),
            "summary": it.get("description") or "",
            "url": it.get("html_url", ""),
            "source": "github_search",
            "bucket": "github",
            "score": 8,
            "extra": f"{it.get('language') or ''} ★{it.get('stargazers_count', 0)}",
        })
    return items


def fetch_hn() -> list[dict]:
    """官方 Firebase API,失败回退 hn.algolia.com(国内更稳)。
    item 详情并发抓取,避免 15 次串行请求。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    try:
        ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            headers=UA, timeout=5).json()[:15]
        items = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(requests.get,
                                 f"https://hacker-news.firebaseio.com/v0/item/{i}.json",
                                 headers=UA, timeout=5) for i in ids[:15]]
            for f in as_completed(futures):
                it = f.result().json()
                if not it or it.get("type") != "story":
                    continue
                items.append({
                    "title": it.get("title", ""),
                    "summary": clean_text(it.get("text") or "", 150),
                    "url": it.get("url") or f"https://news.ycombinator.com/item?id={it.get('id')}",
                    "source": "hacker_news",
                    "bucket": "tech",
                    "topic": "社区讨论",
                    "lang": "en",
                    "score": 7,
                    "extra": f"▲{it.get('score', 0)} 💬{it.get('descendants', 0)}",
                })
        return items
    except Exception:
        r = requests.get("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=15",
                         headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        items = []
        for it in r.json().get("hits", []):
            items.append({
                "title": it.get("title", ""),
                "summary": clean_text(it.get("story_text") or "", 150),
                "url": it.get("url") or f"https://news.ycombinator.com/item?id={it.get('objectID')}",
                "source": "hacker_news",
                "bucket": "tech",
                "topic": "社区讨论",
                "lang": "en",
                "score": 7,
                "extra": f"▲{it.get('points', 0)}",
            })
        return items


def fetch_lobsters() -> list[dict]:
    r = requests.get("https://lobste.rs/hottest.json", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    items = []
    for it in r.json()[:15]:
        items.append({
            "title": it.get("title", ""),
            "summary": (it.get("description") or "")[:150],
            "url": it.get("url") or it.get("short_id_url", ""),
            "source": "lobste_rs",
            "bucket": "tech",
            "topic": "社区讨论",
            "lang": "en",
            "score": 6,
            "extra": f"▲{it.get('score', 0)}",
        })
    return items


# ---------------- 科技 RSS 源(题材多元:AI/开源/消费电子/泛科技) ----------------

TECH_RSS_SOURCES = [
    {"name": "oschina", "url": "https://www.oschina.net/news/rss", "topic": "开源生态", "score": 6, "lang": "zh"},
    {"name": "jiqizhixin", "url": "https://www.jiqizhixin.com/rss", "topic": "AI", "score": 7, "lang": "zh"},
    {"name": "36kr", "url": "https://36kr.com/feed", "topic": "科技创投", "score": 6, "lang": "zh"},
    {"name": "venturebeat", "url": "https://venturebeat.com/feed/", "topic": "AI/半导体", "score": 8, "lang": "en"},
    {"name": "arstechnica", "url": "https://feeds.arstechnica.com/arstechnica/index", "topic": "泛科技", "score": 8, "lang": "en"},
    {"name": "phoronix", "url": "https://www.phoronix.com/rss.php", "topic": "开源/硬件", "score": 7, "lang": "en"},
    {"name": "theverge", "url": "https://www.theverge.com/rss/index.xml", "topic": "消费电子", "score": 8, "lang": "en"},
]

# 科技相关性过滤:命中任一科技词保留;未命中科技词但命中文化/娱乐排除词则剔除
TECH_KEYWORDS = [
    "ai", "人工智能", "模型", "llm", "大模型", "gpt", "openai", "agent", "智能体",
    "芯片", "chip", "半导体", "semiconductor", "gpu", "cpu", "算力", "processor",
    "开源", "open source", "linux", "kernel", "软件", "software", "硬件", "硬件",
    "framework", "api", "编程", "coding", "developer", "代码", "量子", "quantum",
    "机器人", "robot", "自动驾驶", "autonomous", "电动车", "electric vehicle", "电池",
    "数据", "data", "云", "cloud", "网络安全", "security", "黑客", "hack",
    "机器学习", "machine learning", "深度学习", "智能", "smartphone", "手机", "iphone",
    "android", "windows", "macos", "数码", "数字", "digital", "ar", "vr",
    "卫星", "satellite", "航天", "space", "火箭", "rocket", "核聚变", "fusion",
    "微软", "苹果", "谷歌", "英伟达", "nvidia", "tesla", "google", "microsoft", "apple",
    "发布", "发布", "release", "benchmark", "测试", "模型权重", "更新",
]
EXCLUDE_KEYWORDS = [
    "音乐", "album", "song", "instrumental", "电影", "movie", "film", "电视剧", "tv",
    "trailer", "影评", "乐评", "专辑", "演唱会", "体育", "足球", "篮球", "sport",
    "美食", "旅游", "明星", "娱乐圈", "离婚", "文学", "小说", "novel", "艺术展",
    "anime", "漫画", "fashion", "entertainment",
]


def _tech_relevant(title: str, summary: str) -> bool:
    """科技相关性:英文词按单词边界匹配(避免 'ar' 误伤 'nayar'、'ai' 误伤 'said');中文子串匹配。"""
    text = f" {title} {summary} ".lower()
    for k in TECH_KEYWORDS:
        if k.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", text):
                return True
        elif k in text:
            return True
    for k in EXCLUDE_KEYWORDS:
        if k in text:
            return False
    return True  # 无特征词也保留(保守,不误杀)


def fetch_tech_rss() -> list[dict]:
    """批量抓取科技 RSS 源;单源失败静默跳过,不影响整体;含相关性过滤。"""
    import feedparser
    items = []
    for cfg in TECH_RSS_SOURCES:
        try:
            r = requests.get(cfg["url"], headers=UA, timeout=12)
            r.raise_for_status()
            d = feedparser.parse(r.content)
            for e in d.entries[:15]:
                title = (e.get("title") or "").strip()
                if not title:
                    continue
                summary = clean_text(e.get("summary") or e.get("description") or "", 300)
                if not _tech_relevant(title, summary):
                    continue
                link = e.get("link") or ""
                items.append({
                    "title": title,
                    "summary": summary,
                    "url": link,
                    "source": f"rss_{cfg['name']}",
                    "bucket": "tech",
                    "topic": cfg["topic"],
                    "lang": cfg["lang"],
                    "score": cfg["score"],
                    "extra": cfg["topic"],
                })
        except Exception:
            continue  # 单源失败不影响整体
    return items


# ---------------- 微博热搜 ----------------

def fetch_weibo() -> list[dict]:
    attempts = [
        ("https://weibo.com/ajax/side/hotSearch", {"Referer": "https://weibo.com/"},
         lambda d: [
             {"title": it.get("word", ""),
              "summary": f"热度 {it.get('num', '?')}",
              "url": f"https://s.weibo.com/weibo?q=%23{it.get('word', '')}%23",
              "source": "weibo_hot", "bucket": "hot", "score": 5, "extra": ""}
             for it in d.get("data", {}).get("realtime", [])[:20]]),
        ("https://api.vvhan.com/api/hotlist/wbHot", {},
         lambda d: [
             {"title": it.get("title", ""),
              "summary": f"热度 {it.get('hot', '?')}",
              "url": it.get("url", ""),
              "source": "weibo_hot", "bucket": "hot", "score": 5, "extra": ""}
             for it in d.get("data", [])[:20]]),
    ]
    for url, extra_hdrs, parse in attempts:
        try:
            r = requests.get(url, headers={**UA, **extra_hdrs}, timeout=TIMEOUT)
            r.raise_for_status()
            items = parse(r.json())
            if items:
                return items
        except Exception:
            continue
    raise RuntimeError("微博热搜所有候选接口均失败")


# ---------------- 财经(finnews 复用) ----------------

def fetch_finance() -> tuple[list[dict], dict]:
    """直接调 finnews 的源+打分(不走 assemble_report 精选),
    关键词命中优先,其余按分数排序,取前 40 条作为财经候选池。"""
    from finnews.filter import score_items
    from finnews.pipeline import _dedupe_same_batch, _weights, load_config
    from finnews.sources import build_sources
    from finnews.sources.base import make_session

    config = load_config(ROOT / "config.json")
    keywords = config.get("keywords", [])
    session = make_session()
    sources = build_sources(config, session)

    raw_items: list = []
    failures: list[str] = []
    # 三个财经源并行抓取:总耗时 = 最慢单源,而不是三源串行之和
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(src.fetch): src for src in sources}
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                items = fut.result()
                raw_items.extend(items[: int(config.get("max_per_source", 30))])
            except Exception as exc:
                failures.append(f"{src.name}: {exc}")

    raw_items = _dedupe_same_batch(raw_items)
    scored = score_items(raw_items, keywords, dict(_weights(sources)))
    hits = [s for s in scored if s.is_keyword_hit]
    rest = [s for s in scored if not s.is_keyword_hit]

    items = []
    for s in (hits + rest)[:40]:
        items.append({
            "title": s.title,
            "summary": s.summary,
            "url": s.url,
            "source": s.source,
            "bucket": "finance",
            "score": s.score,
            "extra": s.importance,
            "published_at": s.published_at,
        })
    stats = {"total_fetched": len(scored), "keyword_hits": len(hits),
             "source_failures": failures}
    return items, stats


# ---------------- 防编造闸门 ----------------

def _numeric_id(url: str) -> int | None:
    m = re.search(r"/(\d{5,})(?:/|$)", url)
    return int(m.group(1)) if m else None


def check_id_sequence(items: list[dict]) -> bool:
    """同批条目 URL 数字 ID 若连续递增(>=3 个),判定可疑,返回 False。"""
    ids = [i for i in (_numeric_id(it.get("url", "")) for it in items) if i]
    if len(ids) >= 3 and all(ids[i + 1] == ids[i] + 1 for i in range(len(ids) - 1)):
        return False
    return True


def gate(items: list[dict], source: str) -> list[dict]:
    """完整性校验:title/url 缺失或非 http 开头 -> 丢弃。"""
    out = []
    for it in items:
        if not it.get("title") or not it.get("url", "").startswith("http"):
            continue
        out.append(it)
    if source in ("github_trending", "github_search", "hacker_news",
                  "lobste_rs", "weibo_hot", "finnews"):
        if not check_id_sequence(out):
            print(f"  ! 警告:[{source}] URL ID 连续递增,整批标记可疑,已截断保留前 3 条")
            out = out[:3]
    return out


# ---------------- 补抓正文摘要(给 LLM 提供材料) ----------------

def fetch_page_summary(url: str) -> str:
    """从原文 URL 抓取正文摘要:优先 meta description,其次正文前段,最后 <title>。"""
    if not url or not url.startswith("http"):
        return ""
    try:
        r = requests.get(url, headers=UA, timeout=8)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        m = (soup.find("meta", attrs={"name": "description"})
             or soup.find("meta", attrs={"property": "og:description"}))
        if m and m.get("content"):
            d = clean_text(m["content"], 300)
            if len(d) > 20:
                return d
        for tag in ("article", "main"):
            el = soup.find(tag)
            if el:
                t = clean_text(el.get_text(" ", strip=True), 300)
                if len(t) > 40:
                    return t
        ps = soup.find_all("p")
        if ps:
            t = clean_text(" ".join(p.get_text(" ", strip=True) for p in ps[:8]), 300)
            if len(t) > 40:
                return t
        if soup.title and soup.title.string:
            return clean_text(soup.title.string, 120)
        return ""
    except Exception:
        return ""


def enhance_summaries(items: list[dict], max_items: int = 12) -> int:
    """对简述为空的条目并发补抓原文摘要(失败静默,不阻塞流程)。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    targets = [it for it in items
               if not (it.get("summary") or "").strip()
               and it.get("url", "").startswith("http")][:max_items]
    if not targets:
        return 0
    ok = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_page_summary, it["url"]): it for it in targets}
        for f in as_completed(futures):
            it = futures[f]
            s = f.result()
            if s:
                it["summary"] = s
                ok += 1
    return ok


# ---------------- 主流程 ----------------

def main() -> int:
    today = dt.date.today().isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    fetchers = [
        ("github_trending", fetch_github_trending),
        ("github_search", fetch_github_search),
        ("hacker_news", fetch_hn),
        ("lobste_rs", fetch_lobsters),
        ("tech_rss", fetch_tech_rss),
        ("weibo_hot", fetch_weibo),
        ("finance", fetch_finance),
    ]

    result = {"fetched_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
              "sources": {}, "failures": [], "finance_stats": {}}

    # 并发抓取:6 组源并行,总耗时 = 最慢单源(而不是所有源之和)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    started = {name: time.time() for name, _ in fetchers}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fn): name for name, fn in fetchers}
        for fut in as_completed(futures):
            name = futures[fut]
            cost = time.time() - started[name]
            try:
                out = fut.result()
                if name == "finance":
                    fin_items, stats = out
                    result["sources"]["finance"] = {"status": "ok",
                                                    "items": gate(fin_items, "finnews")}
                    result["finance_stats"] = stats
                    print(f"[ok] finance: {len(fin_items)} 条 ({cost:.0f}s) 统计:{stats}")
                else:
                    items = out
                    result["sources"][name] = {"status": "ok", "items": gate(items, name)}
                    print(f"[ok] {name}: {len(items)} 条 ({cost:.0f}s)")
            except Exception as exc:
                result["sources"][name] = {"status": "unavailable", "error": str(exc)[:200],
                                           "items": []}
                result["failures"].append(f"{name}: {exc}")
                print(f"[x] {name}: 暂未获取到 ({cost:.0f}s) -> {exc}")

    # 补抓:对简述为空的科技条目,从原文 URL 并发抓取摘要,给 LLM 提供材料
    tech_items = [it for s in result["sources"].values()
                  for it in s.get("items", []) if it.get("bucket") == "tech"]
    n = enhance_summaries(tech_items)
    if n:
        print(f"[补抓] 为 {n} 条无简述条目抓取了原文摘要")

    out = OUT_DIR / f"{today}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n输出 -> {out}")
    if result["failures"]:
        print(f"共 {len(result['failures'])} 个源失败: " + "; ".join(result["failures"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
