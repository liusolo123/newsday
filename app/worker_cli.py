"""Process entrypoints intended for systemd timers, never for web requests."""
import argparse
import logging
from app.config import Settings
from app.db import build_session_factory
from app.workers.dispatch import dispatch_once
from app.workers.ingest import fetch_and_ingest
from app.workers.publication import prepare_public_news_batch
from app.workers.schedule import schedule_once


log = logging.getLogger("newsday.worker")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("schedule", "dispatch", "ingest", "public-news"))
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    settings = Settings.from_environment()
    if settings.missing_required_values():
        raise RuntimeError("Required deployment settings are missing")
    session = build_session_factory(settings.database_url)()
    try:
        if args.command == "schedule":
            schedule_once(session)
        elif args.command == "dispatch":
            dispatch_once(session, settings.deepseek_api_key, settings.webhook_encryption_key)
        elif args.command == "public-news":
            batch = prepare_public_news_batch(session, settings.deepseek_api_key)
            log.info("public news batch completed: id=%s status=%s", batch.id, batch.status)
        else:
            inserted, failures = fetch_and_ingest(session, args.config)
            session.commit()
            log.info("ingest completed: inserted=%d failed_sources=%d", inserted, len(failures))
            for failure in failures:
                log.warning("ingest source failed: %s", failure)
    finally:
        session.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
