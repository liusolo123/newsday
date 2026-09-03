"""Rate limiting and administrator audit behavior without sensitive storage."""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.models import AuditEvent, Base, RateLimitEvent, User
from app.services.security_controls import (
    RateLimitError,
    enforce_rate_limit,
    recent_audit_events,
    record_audit_event,
)


class SecurityControlTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = Session(engine)

    def tearDown(self) -> None:
        self.session.close()

    def test_rate_limit_hashes_identifier_and_blocks_only_inside_window(self):
        now = datetime.now(timezone.utc)
        for _ in range(2):
            enforce_rate_limit(self.session, "login", "203.0.113.9:reader", "secret", maximum=2, now=now)
        self.session.commit()
        event = self.session.query(RateLimitEvent).first()
        self.assertNotIn("203.0.113.9", event.identifier_hash)
        self.assertEqual(len(event.identifier_hash), 64)
        with self.assertRaises(RateLimitError):
            enforce_rate_limit(self.session, "login", "203.0.113.9:reader", "secret", maximum=2, now=now)
        enforce_rate_limit(
            self.session,
            "login",
            "203.0.113.9:reader",
            "secret",
            maximum=2,
            now=now + timedelta(minutes=16),
        )

    def test_admin_audit_has_no_secret_fields_and_is_displayable(self):
        user = User(
            username="admin",
            normalized_username="admin",
            password_hash=hash_password("a secure password"),
            recovery_code_hash=hash_password("another secure password"),
        )
        self.session.add(user)
        self.session.commit()
        record_audit_event(self.session, user.id, "invite_created", "invite", "safe-id")
        self.session.commit()
        stored = self.session.query(AuditEvent).one()
        self.assertFalse(hasattr(stored, "webhook"))
        self.assertFalse(hasattr(stored, "secret"))
        self.assertEqual(recent_audit_events(self.session)[0]["actor"], "admin")
        self.assertEqual(recent_audit_events(self.session)[0]["action"], "invite_created")


if __name__ == "__main__":
    unittest.main()
