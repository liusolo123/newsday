"""send_feishu.py - 发送早报到飞书
模式A(群自定义机器人 webhook,默认): 以 interactive 卡片发送,更美观
    .env 配置 FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
    加 --text 参数可退回纯文本模式
模式B(自建应用机器人): 纯文本发送
    .env 配置 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_CHAT_ID

用法:
  python send_feishu.py [md路径] [--text]
  python send_feishu.py --list-chats
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

ROOT = Path(__file__).parent
DEFAULT_MD = ROOT / "output" / f"{date.today().isoformat()}.md"
TOKEN_API = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MSG_API = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
CHATS_API = "https://open.feishu.cn/open-apis/im/v1/chats?page_size=50"


def load_env() -> dict:
    env = {}
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("FEISHU_WEBHOOK", "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_CHAT_ID"):
        env.setdefault(k, os.environ.get(k, "").strip())
    return env


# ---------------- 卡片模式 ----------------

def parse_md(text: str) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """解析早报 md:按 ## 板块切分,条目行原样保留;返回 (板块列表, 头部行)。"""
    sections: list[tuple[str, list[str]]] = []
    header_lines: list[str] = []
    cur_title, cur_items = None, []
    for raw in text.splitlines():
        ln = raw.strip()
        if ln.startswith("## "):
            if cur_title is not None:
                sections.append((cur_title, cur_items))
            cur_title, cur_items = ln[3:].strip(), []
        elif cur_title is not None:
            if ln and not ln.startswith(">"):
                cur_items.append(ln)
        else:
            if ln and not ln.startswith("#") and not ln.startswith(">"):
                header_lines.append(ln)
    if cur_title is not None:
        sections.append((cur_title, cur_items))
    return sections, header_lines


def build_cards(text: str) -> list[dict]:
    """按板块构建 interactive 卡片(每板块一张,第一张带总标题与阅读时长)。"""
    sections, header_lines = parse_md(text)
    today = date.today().strftime("%m月%d日")
    cards = []
    for i, (title, items) in enumerate(sections):
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text",
                          "content": f"每日新闻早报 · {today}" if i == 0 else title},
            },
            "elements": [],
        }
        if i == 0 and header_lines:
            card["elements"].append(
                {"tag": "div", "text": {"tag": "lark_md", "content": header_lines[0]}})
            card["elements"].append({"tag": "hr"})
        body = ["**" + title + "**", ""]
        body.extend(items)
        card["elements"].append(
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(body)}})
        cards.append(card)
    return cards


def send_cards_webhook(webhook: str, cards: list[dict]) -> int:
    for card in cards:
        payload = {"msg_type": "interactive", "card": card}
        r = requests.post(webhook, json=payload, timeout=20)
        r.raise_for_status()
        ret = r.json()
        if ret.get("code") != 0:
            print(f"[x] 卡片发送失败: {ret}")
            return 1
    return 0


# ---------------- 文本模式 ----------------

def send_text_webhook(webhook: str, chunks: list[str]) -> int:
    for c in chunks:
        payload = {"msg_type": "text", "content": {"text": c}}
        r = requests.post(webhook, json=payload, timeout=20)
        r.raise_for_status()
        ret = r.json()
        if ret.get("code") != 0:
            print(f"[x] 飞书返回错误: {ret}")
            return 1
    return 0


# ---------------- 自建应用模式 ----------------

def tenant_token(app_id: str, app_secret: str) -> str:
    r = requests.post(TOKEN_API, json={"app_id": app_id, "app_secret": app_secret}, timeout=15)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {d}")
    return d["tenant_access_token"]


def send_text_app(app_id: str, app_secret: str, chat_id: str, chunks: list[str]) -> int:
    token = tenant_token(app_id, app_secret)
    for c in chunks:
        payload = {"receive_id": chat_id, "msg_type": "text",
                   "content": json.dumps({"text": c}, ensure_ascii=False)}
        r = requests.post(MSG_API, json=payload,
                          headers={"Authorization": f"Bearer {token}"}, timeout=20)
        r.raise_for_status()
        ret = r.json()
        if ret.get("code") != 0:
            print(f"[x] 飞书返回错误: {ret}")
            return 1
    return 0


def list_chats(app_id: str, app_secret: str) -> int:
    token = tenant_token(app_id, app_secret)
    r = requests.get(CHATS_API, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    r.raise_for_status()
    d = r.json()
    items = (d.get("data") or {}).get("items") or []
    if not items:
        print("未找到任何群。请先在飞书里创建群,并把应用机器人添加进该群,再重试。")
        return 1
    print("可用群列表(取你要接收早报的群 chat_id):")
    for c in items:
        print(f"  {c.get('chat_id')}  <-  {c.get('name') or '(未命名)'}")
    return 0


# ---------------- 入口 ----------------

def main(argv: list[str]) -> int:
    flags = {a for a in argv[1:] if a.startswith("--")}
    args = [a for a in argv[1:] if not a.startswith("--")]
    env = load_env()

    if "--list-chats" in flags:
        if not env["FEISHU_APP_ID"] or not env["FEISHU_APP_SECRET"]:
            print("[x] --list-chats 需要 .env 中配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
            return 1
        return list_chats(env["FEISHU_APP_ID"], env["FEISHU_APP_SECRET"])

    md = Path(args[0]) if args else DEFAULT_MD
    text = md.read_text(encoding="utf-8")
    chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)]

    if env["FEISHU_WEBHOOK"]:
        if "--text" in flags:
            rc = send_text_webhook(env["FEISHU_WEBHOOK"], chunks)
            mode = "webhook文本"
        else:
            cards = build_cards(text)
            rc = send_cards_webhook(env["FEISHU_WEBHOOK"], cards)
            mode = f"webhook卡片({len(cards)}张)"
    elif env["FEISHU_APP_ID"] and env["FEISHU_APP_SECRET"] and env["FEISHU_CHAT_ID"]:
        rc = send_text_app(env["FEISHU_APP_ID"], env["FEISHU_APP_SECRET"],
                           env["FEISHU_CHAT_ID"], chunks)
        mode = "app"
    else:
        print("[x] 未找到发送配置。请在 .env 中任选一种:")
        print("    模式A: FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx")
        print("    模式B: FEISHU_APP_ID=cli_xxx + FEISHU_APP_SECRET=xxx + FEISHU_CHAT_ID=oc_xxx")
        return 1

    if rc == 0:
        print(f"[ok] 已通过{mode}模式发送: {md.name}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
