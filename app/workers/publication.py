"""Background entrypoint for freezing and polishing the next public-news batch."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsPolish, PublicNewsBatch, PublicNewsSelection
from app.services.publication_snapshots import freeze_public_news_batch
from app.services.publication_workflow import process_public_news_batch


NONRETRYABLE_POLISH_REASONS = (
    "空输出",
    "字数异常",
    "中文不足",
    "含问号",
    "含禁词",
    "新增或变更数字",
    "标题和材料均为空",
)


def _requires_reselection(session: Session, batch: PublicNewsBatch) -> bool:
    """Keep failed batches auditable while replacing candidates that cannot be polished."""
    reasons = session.scalars(
        select(NewsPolish.usage_json["reason"].as_string())
        .join(
            PublicNewsSelection,
            PublicNewsSelection.news_item_id == NewsPolish.news_item_id,
        )
        .where(
            PublicNewsSelection.batch_id == batch.id,
            PublicNewsSelection.polish_status == "failed",
            NewsPolish.prompt_version == batch.prompt_version,
        )
    )
    return any(
        isinstance(reason, str) and reason.startswith(NONRETRYABLE_POLISH_REASONS)
        for reason in reasons
    )


def prepare_public_news_batch(session: Session, api_key: str) -> PublicNewsBatch:
    """Resume an unfinished batch or durably freeze and polish a new one."""
    batch = session.scalar(
        select(PublicNewsBatch)
        .where(PublicNewsBatch.status == "polishing")
        .order_by(PublicNewsBatch.created_at.desc())
        .limit(1)
    )
    if batch is None:
        failed_batch = session.scalar(
            select(PublicNewsBatch)
            .where(PublicNewsBatch.status == "failed")
            .order_by(PublicNewsBatch.created_at.desc())
            .limit(1)
        )
        if failed_batch is not None and not _requires_reselection(session, failed_batch):
            batch = failed_batch
    if batch is None:
        batch = freeze_public_news_batch(session, now=datetime.now(timezone.utc))
        # Save the immutable selection before calling an external model service.
        session.commit()
    result = process_public_news_batch(session, batch.id, api_key)
    session.commit()
    return result
