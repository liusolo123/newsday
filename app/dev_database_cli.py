"""Create the isolated SQLite schema used when local development has no PostgreSQL URL."""

from __future__ import annotations

from app.config import Settings
from app.db import build_engine
from app.models import Base


def ensure_development_database(settings: Settings) -> None:
    """Create local tables without applying production migration workflow."""
    if settings.environment == "production":
        raise RuntimeError("Local development database setup is disabled in production")
    if not settings.database_url.startswith("sqlite"):
        raise RuntimeError("Local development database setup requires a SQLite DATABASE_URL")
    engine = build_engine(settings.database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def main() -> None:
    settings = Settings.from_environment()
    ensure_development_database(settings)


if __name__ == "__main__":
    main()
