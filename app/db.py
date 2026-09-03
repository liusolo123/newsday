"""Database engine and session construction for application services."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def build_engine(database_url: str):
    """Create an engine without opening a database connection eagerly."""
    return create_engine(database_url, pool_pre_ping=True)


def build_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=build_engine(database_url), autoflush=False, expire_on_commit=False)


def session_scope(settings: Settings) -> Generator[Session, None, None]:
    """FastAPI dependency for future request handlers."""
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for database-backed routes")
    session = build_session_factory(settings.database_url)()
    try:
        yield session
    finally:
        session.close()
