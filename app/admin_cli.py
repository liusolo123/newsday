"""Local-only administrator command for invite code lifecycle management."""

import argparse
from getpass import getpass
import json
from typing import Optional
from uuid import UUID

from app.config import Settings
from app.db import build_session_factory
from app.services.admin_invites import create_admin_invite, disable_admin_invite, list_admin_invites


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Newsday invitation codes locally.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create an invitation code.")
    create.add_argument("--max-uses", type=int, default=None, help="Maximum redemption count.")
    commands.add_parser("list", help="List invitation metadata without secrets.")
    disable = commands.add_parser("disable", help="Disable an invitation code by ID.")
    disable.add_argument("invite_id", type=UUID)
    return parser


def run(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_environment()
    missing = settings.missing_required_values()
    if missing:
        raise RuntimeError("Missing required environment values: " + ", ".join(missing))
    session = build_session_factory(settings.database_url)()
    try:
        if args.command == "create":
            code = getpass("邀请码（输入时不会回显）：").strip()
            invite = create_admin_invite(session, code, settings.invite_lookup_key, args.max_uses)
            session.commit()
            print(json.dumps({"id": str(invite.id), "max_uses": invite.max_uses}, ensure_ascii=False))
        elif args.command == "list":
            print(json.dumps(list_admin_invites(session), ensure_ascii=False, indent=2))
        elif args.command == "disable":
            if not disable_admin_invite(session, args.invite_id):
                raise ValueError("Invitation code ID was not found")
            session.commit()
            print(json.dumps({"id": str(args.invite_id), "enabled": False}))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())
