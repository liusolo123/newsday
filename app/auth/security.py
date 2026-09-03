"""Argon2id password handling and non-reversible opaque-token helpers."""

import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
USERNAME_PATTERN = re.compile(r"^[\w.-]{3,32}$", re.UNICODE)


def normalize_username(username: str) -> str:
    candidate = username.strip()
    if not USERNAME_PATTERN.fullmatch(candidate):
        raise ValueError("用户名需为 3–32 个字，可使用文字、数字、点、连字符或下划线")
    return candidate.casefold()


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("密码至少需要 12 个字符")


def hash_password(password: str) -> str:
    validate_password(password)
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def generate_recovery_code() -> str:
    raw = secrets.token_hex(10).upper()
    return "-".join((raw[:5], raw[5:10], raw[10:15], raw[15:]))


def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def invite_lookup_hash(code: str, lookup_key: str) -> str:
    return hmac.new(
        lookup_key.encode("utf-8"), code.strip().upper().encode("utf-8"), hashlib.sha256
    ).hexdigest()
