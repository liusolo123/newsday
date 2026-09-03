"""Transactional account registration, login, and session revocation."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.invites import InviteCodeError, redeem_invite_code
from app.auth.security import (
    generate_recovery_code,
    hash_opaque_token,
    hash_password,
    new_session_token,
    normalize_username,
    verify_password,
)
from app.models import AuthSession, User


SESSION_LIFETIME = timedelta(days=14)


class AuthenticationError(ValueError):
    """A generic error that does not disclose account existence."""


def register_user(
    session: Session, invite_code: str, invite_lookup_key: str, username: str, password: str
) -> Tuple[User, str]:
    normalized_username = normalize_username(username)
    existing = session.scalar(select(User.id).where(User.normalized_username == normalized_username))
    if existing is not None:
        raise ValueError("该用户名已被使用")

    redeem_invite_code(session, invite_code, invite_lookup_key)
    recovery_code = generate_recovery_code()
    user = User(
        username=username.strip(),
        normalized_username=normalized_username,
        password_hash=hash_password(password),
        recovery_code_hash=hash_password(recovery_code),
    )
    session.add(user)
    session.flush()
    return user, recovery_code


def create_login_session(session: Session, username: str, password: str) -> str:
    normalized_username = normalize_username(username)
    user = session.scalar(select(User).where(User.normalized_username == normalized_username))
    if user is None or user.status != "active" or not verify_password(user.password_hash, password):
        raise AuthenticationError("用户名或密码不正确")

    token = new_session_token()
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_opaque_token(token),
            expires_at=datetime.now(timezone.utc) + SESSION_LIFETIME,
        )
    )
    return token


def current_user(session: Session, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    active_session = session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_opaque_token(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(timezone.utc),
        )
    )
    return active_session.user if active_session else None


def revoke_session(session: Session, token: Optional[str]) -> None:
    if not token:
        return
    active_session = session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_opaque_token(token), AuthSession.revoked_at.is_(None)
        )
    )
    if active_session:
        active_session.revoked_at = datetime.now(timezone.utc)

def reset_password_with_recovery_code(session: Session, username: str, recovery_code: str, password: str) -> Optional[str]:
    user = session.scalar(select(User).where(User.normalized_username == normalize_username(username)))
    if user is None or not verify_password(user.recovery_code_hash, recovery_code):
        return None
    user.password_hash = hash_password(password)
    new_recovery_code = generate_recovery_code()
    user.recovery_code_hash = hash_password(new_recovery_code)
    for active_session in user.sessions:
        active_session.revoked_at = datetime.now(timezone.utc)
    return new_recovery_code
