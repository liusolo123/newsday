"""llm_polish.py - 用 DeepSeek 对模板早报逐条润色(严格基于抓取材料,防编造)

流程: 读取 build_report.py 产出的 selected.json → 逐条调 DeepSeek 改写正文
      → 三层防编造校验(输入白盒/数字一致性/禁词+格式) → 通过则替换,失败回退模板
      → 重排版输出 md,覆盖模板版。

无 DEEPSEEK_API_KEY 时自动跳过(纯模板兜底);key 从环境变量或 .env 读取。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

ROOT = Path(__file__).parent
TODAY = date.today().isoformat()
SELECTED = ROOT / "output" / f"{TODAY}.selected.json"
MD_OUT = ROOT / "output" / f"{TODAY}.md"
WPM = 500
MAX_WORKERS = 6
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SOURCE_LABEL = {
    "github_trending": "GitHub Trending", "github_search": "GitHub 搜索",
    "hacker_news": "Hacker News", "lobste_rs": "Lobste.rs",
    "weibo_hot": "微博热搜", "google_news": "Google News 财经",
    "wallstreetcn": "华尔街见闻", "eastmoney_724": "东方财富 7x24",
    "marketwatch": "MarketWatch", "sina_live": "新浪财经 7x24",
}

SYSTEM_PROMPT = (
    "你是严谨的新闻早报编辑。你会收到一条今日抓取到的真实新闻材料，要求改写为 100-200 字的中文新闻段落。硬性规则：\n"
    "1. 只能使用材料中已有的信息，禁止新增任何材料里没有的事实、数字、人名、机构、时间。\n"
    "2. 材料信息不足时，只写材料能支撑的内容，宁可简短，不可虚构。\n"
    "3. 全用陈述句，禁止出现任何问号（？和 ?）。\n"
    "4. 不写「据悉/报道称/消息人士/数据显示/据了解」等无来源引述词。\n"
    "5. 只输出正文段落本身，不要标题、不要解释、不要列表。"
)

BANNED_WORDS = ["据悉", "报道称", "消息人士", "数据显示", "据了解", "业内人士称", "据传", "知情人士"]
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def load_env() -> dict:
    env = {}
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def fix_title(t: str) -> str:
    """标题清洗:合并换行/空白,零问号。"""
    t = re.sub(r"\s+", " ", t).strip()
    if "?" in t or "？" in t:
        t = t.replace("?", "").replace("？", "")
        t = t.rstrip("。.!！ ") + "。"
    return t.strip()


def clean_summary(s: str) -> str:
    """模板兜底简述:取首个不含问号的完整句。"""
    if not s or not s.strip():
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    for end in ("。", "！", "!"):
        idx = s.find(end)
        if 0 < idx <= 140 and "?" not in s[: idx + 1] and "？" not in s[: idx + 1]:
            return s[: idx + 1]
    cut = s[:140].split("。")[0]
    cut = re.split(r"[?？]", cut)[0]
    cut = cut.rstrip("?？")
    return cut if cut else ""


def check_output(text: str, material: str) -> str | None:
    """防编造校验:返回 None=通过,否则返回原因。"""
    if not text or not text.strip():
        return "空输出"
    text = text.strip()
    if not (30 <= len(text) <= 320):
        return f"字数异常({len(text)})"
    if "?" in text or "？" in text:
        return "含问号"
    for w in BANNED_WORDS:
        if w in text:
            return f"含禁词[{w}]"
    # 数字一致性:输出中的数字必须能在材料数字中找到(子串匹配,容忍 155.15 vs 155.1500 的精度差异)
    src_nums = NUM_RE.findall(material)
    out_nums = NUM_RE.findall(text)
    extra = [n for n in out_nums if not any(n in s for s in src_nums)]
    if extra:
        return f"新增数字{extra[:4]}"
    return None


def call_deepseek(title: str, summary: str, source: str, api_key: str) -> str:
    payload = {
        "model": MODEL,
        "temperature": 0.3,
        "max_tokens": 300,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"【新闻标题】{title}\n【材料内容】{summary}\n【来源】{source}"},
        ],
    }
    r = requests.post(API_URL, json=payload,
                      headers={"Authorization": f"Bearer {api_key}"}, timeout=25)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def count_cn(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def main() -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "") or load_env().get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("[polish] 未配置 DEEPSEEK_API_KEY,跳过润色(保持纯模板版)")
        return 0
    if not SELECTED.exists():
        print(f"[polish] 未找到 {SELECTED},请先运行 build_report.py")
        return 1
    data = json.loads(SELECTED.read_text(encoding="utf-8"))

    tasks = []
    hot_n = 0
    for sec in data["sections"]:
        if "热搜" in sec["name"]:  # 热搜板块不润色,原样呈现话题清单
            hot_n = len(sec["items"])
            continue
        for it in sec["items"]:
            # 材料池 = 简述 + 热度/评论数等真实抓取字段(extra),信息不足也不至于无米下锅
            material = " ".join(x for x in ((it.get("summary") or "").strip(),
                                            (it.get("extra") or "").strip()) if x)
            tasks.append((sec["name"], it, material))
    total_n = len(tasks)
    ok, fallback = 0, 0
    reasons: dict[str, int] = {}
    t0 = time.time()

    def work(item: tuple) -> tuple[dict, str | None]:
        _, it, material = item
        title, source = it.get("title", ""), it.get("source", "")
        if not material:
            return it, "材料为空(回退模板)"
        try:
            text = call_deepseek(title, material, source, api_key)
        except Exception as exc:
            return it, f"API异常:{str(exc)[:60]}"
        reason = check_output(text, material)
        if reason is None:
            it["polished"] = text
            return it, None
        return it, reason

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(work, t) for t in tasks]
        for f in as_completed(futures):
            it, reason = f.result()
            if reason is None:
                ok += 1
            else:
                fallback += 1
                key = reason.split(":")[0]
                reasons[key] = reasons.get(key, 0) + 1
                it.pop("polished", None)

    # 重排版 md(标题保持模板清洗版;正文优先 LLM,回退用模板简述)
    blocks = []
    for sec in data["sections"]:
        lines = [f"## {sec['name']}", ""]
        if "热搜" in sec["name"]:  # 热搜:纯话题清单,不润色
            for i, it in enumerate(sec["items"], 1):
                lines.append(f"{i}. {fix_title(it['title'])}")
            blocks.append("\n".join(lines))
            continue
        lines[0] = f"## {sec['name']}（{len(sec['items'])} 条）"
        for i, it in enumerate(sec["items"], 1):
            title = fix_title(it["title"])
            body = (it.get("polished")
                    or clean_summary(it.get("summary", ""))
                    or it.get("extra", "")
                    or "详情暂未获取到")
            src = SOURCE_LABEL.get(it.get("source", ""), it.get("source", ""))
            lines.append(f"{i}. **{title}** — {body}（来源：{src}）")
        blocks.append("\n".join(lines))
    body = "\n\n".join(blocks)
    total_cn = count_cn(body)
    minutes = max(1, round(total_cn / WPM))
    md = [
        f"# 每日新闻早报 · {TODAY}", "",
        f"预计阅读时长：约 {minutes} 分钟 ｜ 新闻 {total_n} 条 ｜ 微博热搜 Top{hot_n}",
        f"> LLM 润色版：正文由 DeepSeek 基于抓取材料改写（润色成功 {ok}/{total_n}，回退 {fallback}），严格限制不新增事实。", "",
        body, "",
        "> 说明：来源被墙/无正文时注明「详情暂未获取到」；数据全部来自当日原始接口直抓。",
    ]
    MD_OUT.write_text("\n".join(md), encoding="utf-8")

    print(f"[polish] 润色成功 {ok}/{total_n} ｜ 回退 {fallback} ｜ 耗时 {time.time()-t0:.0f}s")
    if reasons:
        print(f"[polish] 回退原因统计: {reasons}")
    print(f"[polish] 总字数(中文): {total_cn} ｜ 预计阅读: {minutes} 分钟")

    issues = []
    for q in ("?", "？"):
        for ln in md:
            if q in ln and not ln.startswith("#") and "回退" not in ln:
                issues.append("问号:" + ln[:50])
    if total_cn > 5000:
        issues.append(f"字数超标:{total_cn}")
    if issues:
        print("[polish] !! 终检未通过:")
        for i in issues:
            print("   -", i)
    else:
        print("[polish] 终检通过(问号/字数)")
    print(f"[polish] 输出 -> {MD_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
