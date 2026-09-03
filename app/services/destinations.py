"""Validated, encrypted Feishu and WeCom robot destinations."""

import base64
import os
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Destination, Subscription


class DestinationValidationError(ValueError):
    """Raised for unsafe platform or webhook values."""


class WebhookSendError(RuntimeError):
    """A platform-level rejection with a safe, persistable error code."""

    def __init__(self, code: str, retryable: bool) -> None:
        super().__init__(code)
        self.code = code[:64]
        self.retryable = retryable


def _key(encoded_key: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise DestinationValidationError("Webhook 加密密钥无效") from error
    if len(key) != 32:
        raise DestinationValidationError("Webhook 加密密钥必须为 32 字节")
    return key


def validate_webhook(kind: str, webhook: str) -> str:
    candidate = webhook.strip()
    parsed = urlparse(candidate)
    if parsed.scheme != "https":
        raise DestinationValidationError("Webhook 必须使用 HTTPS")
    valid = (
        kind == "feishu" and parsed.netloc == "open.feishu.cn" and parsed.path.startswith("/open-apis/bot/")
    ) or (
        kind == "wecom" and parsed.netloc == "qyapi.weixin.qq.com" and parsed.path == "/cgi-bin/webhook/send"
    )
    if not valid:
        raise DestinationValidationError("Webhook 地址与所选平台不匹配")
    return candidate


def encrypt_webhook(webhook: str, encoded_key: str) -> tuple[str, str]:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key(encoded_key)).encrypt(nonce, webhook.encode("utf-8"), None)
    return base64.urlsafe_b64encode(ciphertext).decode("ascii"), base64.urlsafe_b64encode(nonce).decode("ascii")


def decrypt_webhook(ciphertext: str, nonce: str, encoded_key: str) -> str:
    try:
        value = AESGCM(_key(encoded_key)).decrypt(
            base64.urlsafe_b64decode(nonce), base64.urlsafe_b64decode(ciphertext), None
        )
        return value.decode("utf-8")
    except Exception as error:
        raise DestinationValidationError("无法解密 Webhook") from error


def mask_webhook(webhook: str) -> str:
    parsed = urlparse(webhook)
    suffix = webhook[-6:] if len(webhook) > 6 else "******"
    return f"{parsed.netloc}/…{suffix}"


def save_destination(session: Session, user_id: UUID, kind: str, webhook: str, encoded_key: str) -> Destination:
    webhook = validate_webhook(kind, webhook)
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if subscription is None:
        raise DestinationValidationError("请先保存新闻订阅配置")
    destination = session.scalar(
        select(Destination).where(Destination.subscription_id == subscription.id, Destination.kind == kind)
    )
    ciphertext, nonce = encrypt_webhook(webhook, encoded_key)
    if destination is None:
        destination = Destination(subscription_id=subscription.id, kind=kind, webhook_ciphertext=ciphertext, webhook_nonce=nonce)
        session.add(destination)
    else:
        destination.webhook_ciphertext = ciphertext
        destination.webhook_nonce = nonce
        destination.verified_at = None
    session.flush()
    return destination


def build_webhook_payload(kind: str, text: str) -> dict:
    if kind == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if kind == "wecom":
        return {"msgtype": "text", "text": {"content": text}}
    raise DestinationValidationError("不支持的发送平台")


def send_webhook(kind: str, webhook: str, text: str) -> None:
    webhook = validate_webhook(kind, webhook)
    response = requests.post(webhook, json=build_webhook_payload(kind, text), timeout=10)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as error:
        raise WebhookSendError("invalid_platform_response", retryable=True) from error
    code_key = "code" if kind == "feishu" else "errcode"
    if payload.get(code_key) != 0:
        raise WebhookSendError(f"{kind}_{payload.get(code_key, 'unknown')}", retryable=False)


def send_test_webhook(kind: str, webhook: str) -> None:
    send_webhook(kind, webhook, "Newsday 测试消息：Webhook 连接正常。")

def mark_destination_verified(session: Session, user_id: UUID, kind: str, webhook: str, encoded_key: str) -> bool:
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if subscription is None:
        return False
    destination = session.scalar(select(Destination).where(Destination.subscription_id == subscription.id, Destination.kind == kind))
    if destination is None or decrypt_webhook(destination.webhook_ciphertext, destination.webhook_nonce, encoded_key) != validate_webhook(kind, webhook):
        return False
    destination.verified_at = datetime.now(timezone.utc)
    return True
