"""Administrator-only invite operations with safe list output."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.invites import create_invite_code
from app.models import InviteCode


def create_admin_invite(
    session: Session, code: str, lookup_key: str, max_uses: Optional[int]
) -> InviteCode:
    invite = create_invite_code(code, lookup_key, max_uses=max_uses)
    session.add(invite)
    session.flush()
    return invite


def disable_admin_invite(session: Session, invite_id: UUID) -> bool:
    invite = session.get(InviteCode, invite_id)
    if invite is None:
        return False
    invite.enabled = False
    return True


def list_admin_invites(session: Session) -> list[dict[str, object]]:
    invites = session.scalars(select(InviteCode).order_by(InviteCode.created_at.desc())).all()
    return [
        {
            "id": str(invite.id),
            "enabled": invite.enabled,
            "max_uses": invite.max_uses,
            "used_count": invite.used_count,
            "created_at": invite.created_at.isoformat() if invite.created_at else None,
        }
        for invite in invites
    ]
