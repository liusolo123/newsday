"""Single dispatch pass; scheduling service invokes this every minute in production."""
from datetime import datetime, timezone
import requests
from sqlalchemy.orm import Session
from app.services.deliveries import claim_due_jobs, destination_webhook, mark_sent, render_delivery, retry_or_fail
from app.services.destinations import WebhookSendError, send_webhook


def delivery_error_details(error: Exception) -> tuple[str, bool]:
    """Return a safe error code and whether an automatic retry is appropriate."""
    if isinstance(error, WebhookSendError):
        return error.code, error.retryable
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else 0
        return f"http_{status or 'error'}", status == 429 or status >= 500
    if isinstance(error, requests.RequestException):
        return "network_error", True
    return type(error).__name__[:64], True

def dispatch_once(session: Session, api_key: str, encryption_key: str) -> int:
    now = datetime.now(timezone.utc)
    jobs = claim_due_jobs(session, now)
    # Persist the claim before the external request. A worker restart cannot then
    # re-send a still-pending job merely because it happened after sending.
    session.commit()
    for job in jobs:
        try:
            kind, webhook = destination_webhook(session, job, encryption_key)
            text = render_delivery(session, job, api_key)
            send_webhook(kind, webhook, text)
            mark_sent(session, job, now)
        except Exception as error:
            error_code, retryable = delivery_error_details(error)
            retry_or_fail(session, job, now, error_code, retryable=retryable)
        session.commit()
    return len(jobs)
