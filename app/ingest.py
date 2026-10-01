"""Validated, batched CSV ingestion for each of the three supplied data sources."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import BusinessHour, StoreStatus, StoreTimezone

BATCH_SIZE = 10_000


def parse_utc_timestamp(raw: str) -> datetime:
    """Parse a source UTC timestamp into the naive-UTC form stored by SQLite."""
    value = raw.strip().replace(" UTC", "+00:00").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include UTC offset: {raw!r}")
    return parsed.astimezone(UTC).replace(tzinfo=None)


def parse_local_time(raw: str) -> time:
    """Parse a business-hours wall-clock time from a CSV field."""
    return time.fromisoformat(raw.strip())


def chunked(rows: Iterator[dict[str, object]], size: int = BATCH_SIZE) -> Iterator[list[dict[str, object]]]:
    """Yield fixed-size row batches to bound memory use during large imports."""
    batch: list[dict[str, object]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def ingest_statuses(session: Session, csv_path: Path) -> int:
    """Upsert status observations from a CSV and return the number of source rows read."""

    def rows() -> Iterator[dict[str, object]]:
        """Validate source status rows lazily so large files are never fully loaded."""
        with csv_path.open(newline="", encoding="utf-8") as source:
            for line_number, row in enumerate(csv.DictReader(source), start=2):
                status = (row.get("status") or "").strip().lower()
                if status not in {"active", "inactive"}:
                    raise ValueError(f"invalid status on line {line_number}: {status!r}")
                yield {
                    "store_id": (row.get("store_id") or "").strip(),
                    "timestamp_utc": parse_utc_timestamp(row.get("timestamp_utc") or ""),
                    "status": status,
                }

    imported = 0
    for batch in chunked(rows()):
        statement = sqlite_insert(StoreStatus).values(batch)
        statement = statement.on_conflict_do_update(
            index_elements=["store_id", "timestamp_utc"],
            set_={"status": statement.excluded.status},
        )
        session.execute(statement)
        imported += len(batch)
    return imported


def ingest_business_hours(session: Session, csv_path: Path) -> int:
    """Replace the business-hours snapshot and return the number of imported rows."""
    rows: list[BusinessHour] = []
    with csv_path.open(newline="", encoding="utf-8") as source:
        for line_number, row in enumerate(csv.DictReader(source), start=2):
            weekday = int(row.get("dayOfWeek") or "-1")
            if weekday not in range(7):
                raise ValueError(f"invalid dayOfWeek on line {line_number}: {weekday}")
            rows.append(BusinessHour(
                store_id=(row.get("store_id") or "").strip(),
                day_of_week=weekday,
                start_time_local=parse_local_time(row.get("start_time_local") or ""),
                end_time_local=parse_local_time(row.get("end_time_local") or ""),
            ))
    session.execute(delete(BusinessHour))
    session.add_all(rows)
    return len(rows)


def ingest_timezones(session: Session, csv_path: Path) -> int:
    """Upsert valid IANA timezone assignments and return the number of source rows read."""
    rows: list[dict[str, object]] = []
    with csv_path.open(newline="", encoding="utf-8") as source:
        for line_number, row in enumerate(csv.DictReader(source), start=2):
            timezone_name = (row.get("timezone_str") or "").strip()
            try:
                ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as error:
                raise ValueError(f"invalid timezone on line {line_number}: {timezone_name!r}") from error
            rows.append({"store_id": (row.get("store_id") or "").strip(), "timezone_str": timezone_name})

    for batch in chunked(iter(rows)):
        statement = sqlite_insert(StoreTimezone).values(batch)
        statement = statement.on_conflict_do_update(
            index_elements=["store_id"],
            set_={"timezone_str": statement.excluded.timezone_str},
        )
        session.execute(statement)
    return len(rows)


def ingest_all(session: Session, status_csv: Path, hours_csv: Path, timezone_csv: Path) -> dict[str, int]:
    """Import all source snapshots atomically and return source row counts by dataset."""
    counts = {
        "business_hours": ingest_business_hours(session, hours_csv),
        "timezones": ingest_timezones(session, timezone_csv),
        "statuses": ingest_statuses(session, status_csv),
    }
    session.commit()
    return counts
