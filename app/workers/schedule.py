"""Run once per minute to create idempotent due delivery jobs."""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.services.deliveries import generate_due_jobs

def schedule_once(session: Session) -> int:
    created = generate_due_jobs(session, datetime.now(timezone.utc))
    session.commit()
    return created
