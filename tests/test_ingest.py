"""Integration tests for source snapshot behavior during CSV ingestion."""

from io import StringIO

from sqlalchemy import select

from app.db import Base, make_session_factory
from app.ingest import ingest_timezones
from app.models import StoreTimezone


class CsvContent:
    """In-memory CSV content that exposes the file interface used by the importer."""

    def __init__(self, content: str) -> None:
        """Store CSV text for a future call to ``open``."""
        self.content = content

    def open(self, **_kwargs: object) -> StringIO:
        """Return a fresh readable CSV stream for each importer call."""
        return StringIO(self.content)


def test_timezone_import_replaces_the_previous_snapshot() -> None:
    """Stores absent from a new timezone file must fall back to the configured default."""
    session_factory = make_session_factory("sqlite://")
    Base.metadata.create_all(session_factory.kw["bind"])
    first_snapshot = CsvContent(
        "store_id,timezone_str\nstore-a,America/New_York\nstore-b,America/Denver\n",
    )
    second_snapshot = CsvContent("store_id,timezone_str\nstore-a,America/Chicago\n")

    with session_factory() as session:
        ingest_timezones(session, first_snapshot)
        session.commit()
        ingest_timezones(session, second_snapshot)
        session.commit()
        imported = session.scalars(select(StoreTimezone).order_by(StoreTimezone.store_id)).all()

    assert [(item.store_id, item.timezone_str) for item in imported] == [
        ("store-a", "America/Chicago"),
    ]
