"""Audit historical source links; mutations require an explicit --apply."""

from __future__ import annotations

import argparse

from app.config import Settings
from app.db import build_session_factory
from app.services.source_link_repair import apply_source_link_repairs, plan_source_link_repairs


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair deterministic historical source links")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the planned deterministic repairs (default: dry-run)",
    )
    args = parser.parse_args()
    settings = Settings.from_environment()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")

    session = build_session_factory(settings.database_url)()
    try:
        plan = plan_source_link_repairs(session)
        applied = apply_source_link_repairs(session, plan) if args.apply else 0
        if args.apply:
            session.commit()
        print(
            "[source-link-repair] "
            f"mode={'apply' if args.apply else 'dry-run'} "
            f"planned={len(plan.repairs)} applied={applied} "
            f"invalid_unrepairable={plan.invalid_unrepairable} unchanged={plan.unchanged}"
        )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
