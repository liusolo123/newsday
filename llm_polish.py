"""以 DeepSeek V4 将每日新闻改写为中文，并保证每条新闻都有中文正文。"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


ROOT = Path(__file__).parent
TODAY = date.today().isoformat()
SELECTED = ROOT / "output" / f"{TODAY}.selected.json"
MD_OUT = ROOT / "output" / f"{TODAY}.md"
WPM = 500
MAX_WORKERS = 6
MAX_REPAIR_ATTEMPTS = 2
API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_PRIMARY_MODEL = "deepseek-v4-flash"
DEFAULT_REPAIR_MODEL = "deepseek-v4-pro"

SOURCE_LABEL = {
    "github_trending": "GitHub Trending", "github_search": "GitHub 搜索",
    "hacker_news": "Hacker News", "lobste_rs": "Lobste.rs",
    "weibo_hot": "微博热搜", "google_news": "Google News 财经",
    "wallstreetcn": "华尔街见闻", "eastmoney_724": "东方财富 7x24",
    "marketwatch": "MarketWatch", "sina_live": "新浪财经 7x24",
}

SYSTEM_PROMPT = """你是严谨的中文新闻早报编辑。将提供的真实新闻材料改写为中文正文。
硬性规则：
1. 只能使用标题和材料中已有的信息，禁止补充事实、数字、人名、机构、时间或因果关系。
2. 即使原文为英文，正文也必须使用中文；产品名、项目名和专有名词可以保留原文。
3. 材料不足时只写可支撑的内容，宁可简短，不可虚构。
4. 使用陈述句，不得出现问号（？或 ?）。
5. 不写“据悉、报道称、消息人士、数据显示、据了解、业内人士称、据传、知情人士”。
6. 只输出 20 至 260 个字符的正文段落，不要标题、解释、列表或 Markdown。"""

REPAIR_PROMPT = """你是严谨的中文新闻编辑，正在修复一段不合格摘要。
仅用标题和材料中的事实重写中文正文，并严格修复给出的校验问题。
不得增加任何数字、事实、人物、机构、时间或推断；不得出现问号、禁用引述词、标题、解释、列表或 Markdown。
只输出 20 至 260 个字符的中文正文段落。"""

BANNED_WORDS = ["据悉", "报道称", "消息人士", "数据显示", "据了解", "业内人士称", "据传", "知情人士"]
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


@dataclass(frozen=True)
class PolishResult:
    text: str
    status: str
    reason: str = ""


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def config_value(name: str, file_env: dict[str, str], default: str = "") -> str:
    return os.environ.get(name, "").strip() or file_env.get(name, "").strip() or default


def fix_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    if "?" in title or "？" in title:
        title = title.replace("?", "").replace("？", "")
        title = title.rstrip("。.!！ ") + "。"
    return title


def count_cn(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def normalize_number(value: str) -> str:
    return value.replace(",", "").rstrip("%")


def numbers_are_supported(text: str, material: str) -> bool:
    source_numbers = [normalize_number(value) for value in NUM_RE.findall(material)]
    for value in NUM_RE.findall(text):
        normalized = normalize_number(value)
        if normalized not in source_numbers:
            return False
    return True


def check_output(text: str, material: str) -> str | None:
    """验证文本为安全、可展示的中文新闻正文；None 表示通过。"""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return "空输出"
    if not (20 <= len(text) <= 260):
        return f"字数异常({len(text)})"
    if count_cn(text) < 10:
        return "中文不足"
    if "?" in text or "？" in text:
        return "含问号"
    for word in BANNED_WORDS:
        if word in text:
            return f"含禁词[{word}]"
    if not numbers_are_supported(text, material):
        return "新增或变更数字"
    return None


def call_deepseek(
    *,
    title: str,
    material: str,
    source: str,
    api_key: str,
    model: str,
    system_prompt: str,
    previous_text: str = "",
    failure_reason: str = "",
) -> str:
    user_content = f"【新闻标题】{title}\n【材料内容】{material}\n【来源】{source}"
    if previous_text or failure_reason:
        user_content += (
            f"\n【上一稿】{previous_text or '无'}"
            f"\n【必须修复的问题】{failure_reason or '重新检查事实与中文表达'}"
        )
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 400,
        "thinking": {"type": "disabled"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    response = requests.post(
        API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("DeepSeek 返回格式异常") from exc
    if not isinstance(content, str):
        raise RuntimeError("DeepSeek 未返回文本内容")
    return content.strip()


def chinese_fallback() -> str:
    """在材料或模型不可用时，保证展示层仍有不虚构的中文说明。"""
    return "该新闻的原始材料不足或润色服务暂不可用，暂未生成完整摘要，请通过原文链接查看详情。"


def polish_item(
    *,
    title: str,
    material: str,
    source: str,
    api_key: str,
    primary_model: str,
    repair_model: str,
) -> PolishResult:
    source_material = f"{title}\n{material}".strip()
    if not source_material:
        return PolishResult(chinese_fallback(), "fallback", "标题和材料均为空")
    if not api_key:
        return PolishResult(chinese_fallback(), "fallback", "未配置 API Key")

    previous_text = ""
    failure_reason = ""
    attempts = [(primary_model, SYSTEM_PROMPT, "flash")]
    attempts.extend((repair_model, REPAIR_PROMPT, "pro") for _ in range(MAX_REPAIR_ATTEMPTS))

    for model, prompt, status in attempts:
        try:
            text = call_deepseek(
                title=title,
                material=material,
                source=source,
                api_key=api_key,
                model=model,
                system_prompt=prompt,
                previous_text=previous_text,
                failure_reason=failure_reason,
            )
        except Exception as exc:
            failure_reason = f"API异常:{str(exc)[:80]}"
            continue
        failure_reason = check_output(text, source_material) or ""
        if not failure_reason:
            return PolishResult(text, status)
        previous_text = text

    return PolishResult(chinese_fallback(), "fallback", failure_reason or "润色失败")


def render_report(data: dict, total_news: int, stats: Counter[str]) -> str:
    blocks = []
    for section in data["sections"]:
        lines = [f"## {section['name']}", ""]
        if "热搜" in section["name"]:
            for index, item in enumerate(section["items"], 1):
                lines.append(f"{index}. {fix_title(item['title'])}")
            blocks.append("\n".join(lines))
            continue
        lines[0] = f"## {section['name']}（{len(section['items'])} 条）"
        for index, item in enumerate(section["items"], 1):
            title = fix_title(item["title"])
            body = item.get("polished") or chinese_fallback()
            source = SOURCE_LABEL.get(item.get("source", ""), item.get("source", ""))
            lines.append(f"{index}. **{title}** — {body}（来源：{source}）")
        blocks.append("\n".join(lines))

    body = "\n\n".join(blocks)
    hot_count = sum(
        len(section["items"]) for section in data["sections"] if "热搜" in section["name"]
    )
    total_cn = count_cn(body)
    minutes = max(1, round(total_cn / WPM))
    return "\n".join([
        f"# 每日新闻早报 · {TODAY}", "",
        f"预计阅读时长：约 {minutes} 分钟 ｜ 新闻 {total_news} 条 ｜ 微博热搜 Top{hot_count}",
        (
            "> DeepSeek V4 中文润色版："
            f"Flash 成功 {stats['flash']}/{total_news}，"
            f"Pro 修复 {stats['pro']}，中文兜底 {stats['fallback']}。"
        ),
        "",
        body,
        "",
        "> 说明：正文仅依据当日抓取材料生成；材料或服务不可用时以中文说明兜底。",
    ])


def main() -> int:
    file_env = load_env()
    api_key = config_value("DEEPSEEK_API_KEY", file_env)
    primary_model = config_value("DEEPSEEK_PRIMARY_MODEL", file_env, DEFAULT_PRIMARY_MODEL)
    repair_model = config_value("DEEPSEEK_REPAIR_MODEL", file_env, DEFAULT_REPAIR_MODEL)
    if not SELECTED.exists():
        print(f"[polish] 未找到 {SELECTED}，请先运行 build_report.py")
        return 1
    if not api_key:
        print("[polish] 未配置 DEEPSEEK_API_KEY，将使用中文安全兜底")

    data = json.loads(SELECTED.read_text(encoding="utf-8"))
    tasks: list[tuple[dict, str]] = []
    for section in data["sections"]:
        if "热搜" in section["name"]:
            continue
        for item in section["items"]:
            material = " ".join(
                value for value in ((item.get("summary") or "").strip(), (item.get("extra") or "").strip())
                if value
            )
            tasks.append((item, material))

    total_news = len(tasks)
    stats: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    started_at = time.monotonic()

    def work(item: dict, material: str) -> tuple[dict, PolishResult]:
        result = polish_item(
            title=item.get("title", ""),
            material=material,
            source=item.get("source", ""),
            api_key=api_key,
            primary_model=primary_model,
            repair_model=repair_model,
        )
        return item, result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(work, item, material) for item, material in tasks]
        for future in as_completed(futures):
            item, result = future.result()
            item["polished"] = result.text
            stats[result.status] += 1
            if result.reason:
                reasons[result.reason.split(":")[0]] += 1

    report = render_report(data, total_news, stats)
    MD_OUT.write_text(report, encoding="utf-8")
    print(
        f"[polish] Flash 成功 {stats['flash']}/{total_news} ｜ "
        f"Pro 修复 {stats['pro']} ｜ 中文兜底 {stats['fallback']} ｜ "
        f"耗时 {time.monotonic() - started_at:.0f}s"
    )
    if reasons:
        print(f"[polish] 兜底原因统计: {dict(reasons)}")
    print(f"[polish] 使用模型: Flash={primary_model}，Pro={repair_model}")
    print(f"[polish] 输出 -> {MD_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
