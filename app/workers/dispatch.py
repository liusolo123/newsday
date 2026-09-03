"""Single dispatch pass; scheduling service invokes this every minute in production."""
from datetime import datetime, timezone
import requests
from sqlalchemy.orm import Session
from app.services.deliveries import claim_due_jobs, destination_webhook, mark_sent, render_delivery, retry_or_fail

def dispatch_once(session: Session, api_key: str, encryption_key: str) -> int:
    now = datetime.now(timezone.utc)
    jobs = claim_due_jobs(session, now)
    for job in jobs:
        try:
            kind, webhook = destination_webhook(session, job, encryption_key)
            text = render_delivery(session, job, api_key)
            payload = {"msg_type":"text","content":{"text":text}} if kind == "feishu" else {"msgtype":"text","text":{"content":text}}
            response = requests.post(webhook, json=payload, timeout=10)
            response.raise_for_status()
            mark_sent(session, job, now)
        except Exception as error:
            retry_or_fail(session, job, now, type(error).__name__)
    session.commit()
    return len(jobs)
