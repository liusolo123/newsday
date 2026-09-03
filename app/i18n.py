"""Small, explicit translation catalogue for the public web foundation."""

from typing import Literal


Locale = Literal["zh", "en"]
SUPPORTED_LOCALES = frozenset({"zh", "en"})


def resolve_locale(value: str) -> Locale:
    """Return a supported locale, preferring Chinese for unknown paths."""
    return value if value in SUPPORTED_LOCALES else "zh"  # type: ignore[return-value]


def alternate_locale(locale: Locale) -> Locale:
    return "en" if locale == "zh" else "zh"


TRANSLATIONS: dict[Locale, dict[str, object]] = {
    "zh": {
        "language_name": "中文",
        "language_switch": "English",
        "brand_note": "个人新闻操作系统",
        "navigation": [
            ("topics", "主题"),
            ("how-it-works", "如何运作"),
            ("subscription", "创建订阅"),
        ],
        "hero_title": "读真正推动你的信息。",
        "hero_highlight": "你的信息。",
        "hero_copy": "把每天真正影响你的信息，压缩成一份可以选择、可以掌控、准时送达的中文新闻摘要。",
        "primary_action": "配置我的订阅",
        "secondary_action": "浏览今日内容",
        "next_delivery": "下一次投递",
        "delivery_detail": "北京时间 · 3 个已选主题",
        "delivery_destination": "飞书机器人",
        "delivery_state": "准备就绪",
        "library_label": "精选内容库 / 今日",
        "library_title": "浏览你的信息流。",
        "library_action": "构建你的组合",
        "topics": [
            ("AI", "AI", "大模型、智能体与真正落地的变化。"),
            ("科技", "科技", "软件、芯片、云与值得继续追踪的创新。"),
            ("财经", "财经", "宏观、公司和影响判断的经济信号。"),
            ("投资市场", "投资市场", "市场走势、资产变化与关键的风险提示。"),
            ("GitHub", "GitHub", "开源项目、开发者工具和快速上升的社区趋势。"),
            ("社会热搜", "社会热搜", "热点的来源与可信状态，会被明确标注。"),
        ],
        "how_label": "为真实订阅准备",
        "how_title": "十个主题。每天最多三次。一份你会打开的简报。",
        "how_steps": [
            ("01", "选择主题", "从 AI、科技、财经到 GitHub，按每类 5–10 条搭配。"),
            ("02", "设定时间", "所有投递均以北京时间进行，每天最多三个时间点。"),
            ("03", "连接平台", "首版支持飞书和企业微信的官方群机器人。"),
        ],
        "subscription_label": "邀请制订阅",
        "subscription_title": "你的信号，从这里开始。",
        "subscription_copy": "输入邀请码后创建账户，选择主题、发送时间与平台。公开新闻浏览始终无需邀请码。",
        "subscription_action": "使用邀请码开始订阅",
        "footer": "NEWS//DAY · 由你决定每天接收什么",
    },
    "en": {
        "language_name": "English",
        "language_switch": "中文",
        "brand_note": "Personal news operating system",
        "navigation": [
            ("topics", "Topics"),
            ("how-it-works", "How it works"),
            ("subscription", "Create subscription"),
        ],
        "hero_title": "Read what moves you.",
        "hero_highlight": "moves you.",
        "hero_copy": "Turn the signals that matter into a Chinese news briefing you can choose, control, and receive on time.",
        "primary_action": "Build my briefing",
        "secondary_action": "Explore today",
        "next_delivery": "Next delivery",
        "delivery_detail": "Asia / Shanghai · 3 selected tracks",
        "delivery_destination": "Feishu bot",
        "delivery_state": "Ready",
        "library_label": "Curated library / Today",
        "library_title": "Explore your feed.",
        "library_action": "Build your mix",
        "topics": [
            ("AI", "AI", "Models, agents, and the changes actually reaching the world."),
            ("Technology", "Technology", "Software, chips, cloud, and innovation worth following."),
            ("Business", "Business", "Macro, companies, and economic signals that inform a view."),
            ("Markets", "Markets", "Market moves, asset changes, and the risks that matter."),
            ("GitHub", "GitHub", "Open-source projects, developer tools, and rising community trends."),
            ("Social trends", "Social trends", "The source and confidence level behind a trending story stay visible."),
        ],
        "how_label": "Built for a real subscription",
        "how_title": "Ten tracks. Up to three deliveries. One briefing you'll open.",
        "how_steps": [
            ("01", "Choose tracks", "Mix AI, technology, business, markets, GitHub, and more—5–10 items each."),
            ("02", "Set a time", "Every delivery uses Asia / Shanghai time, up to three times a day."),
            ("03", "Connect a platform", "The first release supports official Feishu and WeCom group bots."),
        ],
        "subscription_label": "Invitation-only subscription",
        "subscription_title": "Your signal starts here.",
        "subscription_copy": "Use an invitation to create an account, choose tracks, set delivery times, and connect a platform. Public news browsing remains open to everyone.",
        "subscription_action": "Start with an invitation",
        "footer": "NEWS//DAY · Decide what reaches you each day",
    },
}
