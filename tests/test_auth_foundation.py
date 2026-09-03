"""Security and database-constraint tests for the account foundation."""

import unittest
from uuid import UUID
import base64

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.invites import InviteCodeError, create_invite_code, redeem_invite_code
from app.auth.security import (
    generate_recovery_code,
    hash_opaque_token,
    hash_password,
    new_session_token,
    normalize_username,
    verify_password,
)
from app.config import Settings
from app.models import Base, SubscriptionCategory, User
from app.services.accounts import AuthenticationError, create_login_session, current_user, register_user, reset_password_with_recovery_code, revoke_session
from app.services.admin_invites import create_admin_invite, disable_admin_invite, list_admin_invites
from app.services.subscriptions import SubscriptionValidationError, load_subscription, save_subscription
from app.services.destinations import decrypt_webhook, encrypt_webhook, validate_webhook


class AccountFoundationTests(unittest.TestCase):
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

    def test_password_and_recovery_code_use_argon2id_hashes(self) -> None:
        password_hash = hash_password("a secure password")
        recovery_code = generate_recovery_code()
        recovery_hash = hash_password(recovery_code)

        self.assertTrue(password_hash.startswith("$argon2id$"))
        self.assertTrue(verify_password(password_hash, "a secure password"))
        self.assertFalse(verify_password(password_hash, "incorrect password"))
        self.assertTrue(verify_password(recovery_hash, recovery_code))

    def test_username_is_casefolded_and_uniquely_constrained(self) -> None:
        self.assertEqual(normalize_username("  新闻User  "), "新闻user")
        first = User(
            username="新闻User",
            normalized_username=normalize_username("新闻User"),
            password_hash=hash_password("a secure password"),
            recovery_code_hash=hash_password("another secure password"),
        )
        self.session.add(first)
        self.session.commit()
        duplicate = User(
            username="新闻user",
            normalized_username=normalize_username("新闻user"),
            password_hash=hash_password("a secure password"),
            recovery_code_hash=hash_password("another secure password"),
        )
        self.session.add(duplicate)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_invite_is_hashed_and_cannot_be_redeemed_past_its_limit(self) -> None:
        invite = create_invite_code("newsday-2026", "lookup-key", max_uses=1)
        self.assertNotIn("newsday-2026", invite.lookup_hash)
        self.assertNotIn("newsday-2026", invite.secret_hash)
        self.session.add(invite)
        self.session.commit()
        redeemed = redeem_invite_code(self.session, "NEWSDAY-2026", "lookup-key")
        self.session.commit()
        self.assertEqual(redeemed.used_count, 1)
        with self.assertRaises(InviteCodeError):
            redeem_invite_code(self.session, "newsday-2026", "lookup-key")

    def test_category_limits_are_enforced_by_the_database(self) -> None:
        invalid = SubscriptionCategory(
            subscription_id=UUID("00000000-0000-0000-0000-000000000001"), category="ai", item_limit=4
        )
        self.session.add(invalid)
        with self.assertRaises(IntegrityError):
            self.session.commit()

    def test_opaque_session_tokens_are_unique_and_not_stored_raw(self) -> None:
        first = new_session_token()
        second = new_session_token()
        self.assertNotEqual(first, second)
        self.assertEqual(len(hash_opaque_token(first)), 64)
        self.assertNotEqual(first, hash_opaque_token(first))

    def test_empty_environment_is_never_considered_ready_for_production(self) -> None:
        settings = Settings("", "", "", "")

        self.assertEqual(
            settings.missing_required_values(),
            ("DATABASE_URL", "APP_SESSION_SECRET", "INVITE_LOOKUP_KEY", "WEBHOOK_ENCRYPTION_KEY"),
        )

    def test_registration_login_and_logout_are_transactional(self) -> None:
        invite = create_invite_code("account-2026", "lookup-key", max_uses=1)
        self.session.add(invite)
        self.session.commit()
        user, recovery_code = register_user(
            self.session, "account-2026", "lookup-key", "Reader", "a secure password"
        )
        self.session.commit()
        self.assertTrue(verify_password(user.recovery_code_hash, recovery_code))
        token = create_login_session(self.session, "reader", "a secure password")
        self.session.commit()
        self.assertEqual(current_user(self.session, token).id, user.id)
        revoke_session(self.session, token)
        self.session.commit()
        self.assertIsNone(current_user(self.session, token))
        with self.assertRaises(AuthenticationError):
            create_login_session(self.session, "reader", "incorrect password")

    def test_recovery_code_resets_password_and_revokes_old_sessions(self) -> None:
        invite = create_invite_code("recover-2026", "lookup-key"); self.session.add(invite); self.session.commit()
        user, code = register_user(self.session, "recover-2026", "lookup-key", "recover", "a secure password"); token = create_login_session(self.session, "recover", "a secure password"); self.session.commit()
        new_code = reset_password_with_recovery_code(self.session, "recover", code, "a replacement password")
        self.session.commit()
        self.assertIsNone(current_user(self.session, token)); self.assertTrue(verify_password(user.recovery_code_hash, new_code))

    def test_administrator_invite_listing_never_exposes_hashes(self) -> None:
        invite = create_admin_invite(self.session, "private-2026", "lookup-key", max_uses=3)
        self.session.commit()
        listing = list_admin_invites(self.session)
        self.assertEqual(listing[0]["id"], str(invite.id))
        self.assertNotIn("lookup_hash", listing[0])
        self.assertNotIn("secret_hash", listing[0])
        self.assertTrue(disable_admin_invite(self.session, invite.id))
        self.session.commit()
        self.assertFalse(list_admin_invites(self.session)[0]["enabled"])

    def test_subscription_limits_and_times_are_saved_server_side(self) -> None:
        user = User(username="subscriber", normalized_username="subscriber", password_hash=hash_password("a secure password"), recovery_code_hash=hash_password("another secure password"))
        self.session.add(user)
        self.session.commit()
        saved = save_subscription(self.session, user.id, {"ai": 6, "github": 7}, ["18:30", "08:00", ""])
        self.session.commit()
        self.assertEqual([item.local_time.strftime("%H:%M") for item in saved.schedules], ["08:00", "18:30"])
        self.assertEqual(sum(item.item_limit for item in load_subscription(self.session, user.id).categories), 13)
        with self.assertRaises(SubscriptionValidationError):
            save_subscription(self.session, user.id, {"ai": 10, "github": 10, "technology": 10, "business": 10, "markets": 10, "sports": 10}, ["08:00"])

    def test_webhook_is_validated_and_reversibly_encrypted_only_with_the_key(self) -> None:
        webhook = validate_webhook("feishu", "https://open.feishu.cn/open-apis/bot/v2/hook/example")
        key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
        ciphertext, nonce = encrypt_webhook(webhook, key)
        self.assertNotIn(webhook, ciphertext)
        self.assertEqual(decrypt_webhook(ciphertext, nonce, key), webhook)


if __name__ == "__main__":
    unittest.main()
