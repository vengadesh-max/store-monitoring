"""Database engine, session factory, and request-scoped session dependency."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class shared by all SQLAlchemy ORM entities."""

    pass


def make_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """Create a configured SQLAlchemy session factory for the supplied database URL."""
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _record) -> None:  # type: ignore[no-untyped-def]
            """Enable SQLite settings that support integrity and concurrent readers."""
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return sessionmaker(engine, expire_on_commit=False)


SessionFactory = make_session_factory()


def get_db() -> Generator[Session, None, None]:
    """Yield one database session per request and always close it afterwards."""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
