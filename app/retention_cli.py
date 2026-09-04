"""Daily retention command; defaults to a no-write preview."""
import argparse
from pathlib import Path
from app.config import Settings
from app.db import build_session_factory
from app.services.retention import cleanup_expired_news

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true"); parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1]); parser.add_argument("--retention-days", type=int, default=7); parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args(); settings = Settings.from_environment()
    if not settings.database_url: raise RuntimeError("DATABASE_URL is required")
    session = build_session_factory(settings.database_url)()
    try:
        result = cleanup_expired_news(session, apply=args.apply, root=args.root, retention_days=args.retention_days, batch_size=args.batch_size)
        if args.apply: session.commit()
        print(result)
    except Exception as error:
        session.rollback()
        message = f"[retention] failed: {type(error).__name__}"
        print(message)
        try:
            from ops_maintenance import send_alert
            send_alert(message)
        except Exception:
            pass
        return 1
    finally: session.close()
    return 0
if __name__ == "__main__": raise SystemExit(main())
