"""Daily retention command; defaults to a no-write preview."""
import argparse
from app.config import Settings
from app.db import build_session_factory
from app.services.retention import cleanup_expired_news

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(); settings = Settings.from_environment()
    if not settings.database_url: raise RuntimeError("DATABASE_URL is required")
    session = build_session_factory(settings.database_url)()
    try:
        result = cleanup_expired_news(session, apply=args.apply)
        if args.apply: session.commit()
        print(result)
    finally: session.close()
    return 0
if __name__ == "__main__": raise SystemExit(main())
