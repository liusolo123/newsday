"""Controlled administrator management for the fixed, classifier-supported categories."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CategoryPreset
from app.models.subscription import CATEGORY_VALUES


DEFAULT_PRESETS = (
    ("ai", "AI", "AI", 10),
    ("technology", "科技", "Technology", 20),
    ("consumer_electronics", "消费电子", "Consumer electronics", 30),
    ("github", "GitHub", "GitHub", 40),
    ("business", "财经", "Business", 50),
    ("markets", "投资市场", "Markets", 60),
    ("politics", "时政", "Politics", 70),
    ("sports", "体育", "Sports", 80),
    ("entertainment", "娱乐", "Entertainment", 90),
    ("social_trends", "社会热搜", "Social trends", 100),
)


def ensure_category_presets(session: Session) -> None:
    existing = set(session.scalars(select(CategoryPreset.key)))
    for key, label_zh, label_en, sort_order in DEFAULT_PRESETS:
        if key not in existing:
            session.add(
                CategoryPreset(
                    key=key,
                    label_zh=label_zh,
                    label_en=label_en,
                    enabled=True,
                    sort_order=sort_order,
                )
            )
    session.flush()


def category_presets(session: Session, *, include_disabled: bool = True) -> list[CategoryPreset]:
    ensure_category_presets(session)
    query = select(CategoryPreset).order_by(CategoryPreset.sort_order, CategoryPreset.key)
    if not include_disabled:
        query = query.where(CategoryPreset.enabled.is_(True))
    return list(session.scalars(query))


def category_choices(session: Session, locale: str, *, include_disabled: bool = False) -> list[tuple[str, str]]:
    label = "label_zh" if locale == "zh" else "label_en"
    return [(preset.key, getattr(preset, label)) for preset in category_presets(session, include_disabled=include_disabled)]


def update_category_preset(
    session: Session,
    key: str,
    *,
    label_zh: str,
    label_en: str,
    sort_order: int,
    enabled: bool,
) -> bool:
    if key not in CATEGORY_VALUES or not label_zh.strip() or not label_en.strip() or sort_order < 0:
        return False
    ensure_category_presets(session)
    preset = session.get(CategoryPreset, key)
    if preset is None:
        return False
    preset.label_zh = label_zh.strip()[:64]
    preset.label_en = label_en.strip()[:64]
    preset.sort_order = sort_order
    preset.enabled = enabled
    session.flush()
    return True
