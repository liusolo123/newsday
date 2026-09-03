"""Safe invitation creation and one-time redemption operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Optional

from app.auth.security import PASSWORD_HASHER, invite_lookup_hash, verify_password
from app.models import InviteCode


class InviteCodeError(ValueError):
    """Raised without revealing whether a specific invitation exists."""


def create_invite_code(code: str, lookup_key: str, max_uses: Optional[int] = None) -> InviteCode:
    normalized_code = code.strip().upper()
    if len(normalized_code) < 6:
        raise ValueError("邀请码至少需要 6 个字符")
    if max_uses is not None and max_uses < 1:
        raise ValueError("邀请码使用次数必须大于 0")
    return InviteCode(
        lookup_hash=invite_lookup_hash(normalized_code, lookup_key),
        secret_hash=PASSWORD_HASHER.hash(normalized_code),
        max_uses=max_uses,
    )


def redeem_invite_code(session: Session, code: str, lookup_key: str) -> InviteCode:
    normalized_code = code.strip().upper()
    lookup = invite_lookup_hash(normalized_code, lookup_key)
    invite = session.scalar(select(InviteCode).where(InviteCode.lookup_hash == lookup).with_for_update())
    if invite is None or not invite.enabled or not verify_password(invite.secret_hash, normalized_code):
        raise InviteCodeError("邀请码无效或不可用")
    if invite.max_uses is not None and invite.used_count >= invite.max_uses:
        raise InviteCodeError("邀请码无效或不可用")
    invite.used_count += 1
    return invite
