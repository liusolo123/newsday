"""Create local-only public news records for front-end development."""

from __future__ import annotations

from app.config import Settings
from app.db import build_session_factory
from app.services.dev_seed import seed_development_public_news


def main() -> None:
    settings = Settings.from_environment()
    if settings.environment == "production":
        raise RuntimeError("Development seed data is disabled when APP_ENV=production")
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to create development seed data")
    session = build_session_factory(settings.database_url)()
    try:
        batch = seed_development_public_news(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    print(f"Local development news batch is ready: {batch.id}")


if __name__ == "__main__":
    main()
