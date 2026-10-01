"""Report service implementing business-hour intersection and poll interpolation."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased, sessionmaker

from app.config import get_settings
from app.models import BusinessHour, Report, StoreStatus, StoreTimezone

WINDOWS = (
    ("last_hour", timedelta(hours=1), "minutes"),
    ("last_day", timedelta(days=1), "hours"),
    ("last_week", timedelta(days=7), "hours"),
)
CSV_HEADER = [
    "store_id",
    "uptime_last_hour(in minutes)",
    "uptime_last_day(in hours)",
    "update_last_week(in hours)",
    "downtime_last_hour(in minutes)",
    "downtime_last_day(in hours)",
    "downtime_last_week(in hours)",
]


@dataclass(frozen=True)
class Reading:
    """An in-memory status observation used by interpolation calculations."""

    timestamp: datetime
    status: str


@dataclass(frozen=True)
class Interval:
    """A half-open UTC time interval represented by naive UTC datetimes."""

    start: datetime
    end: datetime


def utc_now_naive() -> datetime:
    """Return the current instant in the naive-UTC representation used by the database."""
    return datetime.now(UTC).replace(tzinfo=None)


def _valid_local_instants(local_value: datetime, timezone: ZoneInfo) -> list[datetime]:
    """Return every real UTC instant represented by a local wall-clock value."""
    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = local_value.replace(tzinfo=timezone, fold=fold)
        round_tripped = candidate.astimezone(UTC).astimezone(timezone).replace(tzinfo=None)
        if round_tripped == local_value:
            candidates.append(candidate.astimezone(UTC).replace(tzinfo=None))
    return sorted(set(candidates))


def local_boundary(local_day: date, local_time: time, timezone: ZoneInfo, *, is_end: bool) -> datetime:
    """Convert a wall-clock boundary to UTC, making daylight-saving behavior explicit.

    Ambiguous fall-back boundaries use the earlier instant for an opening and later instant
    for a closing. A nonexistent spring-forward wall time advances to the first valid minute.
    """
    value = datetime.combine(local_day, local_time)
    for _ in range(181):
        candidates = _valid_local_instants(value, timezone)
        if candidates:
            return candidates[-1] if is_end else candidates[0]
        value += timedelta(minutes=1)
    raise ValueError(f"could not resolve local time {value} in {timezone.key}")


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    """Sort and union overlapping or adjacent intervals to prevent double counting."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: item.start)
    merged = [ordered[0]]
    for interval in ordered[1:]:
        current = merged[-1]
        if interval.start <= current.end:
            merged[-1] = Interval(current.start, max(current.end, interval.end))
        else:
            merged.append(interval)
    return merged


def business_intervals(
    window_start: datetime,
    window_end: datetime,
    timezone: ZoneInfo,
    hours: list[BusinessHour],
) -> list[Interval]:
    """Return the union of local business-hour intervals clipped to a UTC report window."""
    if not hours:
        return [Interval(window_start, window_end)]

    by_weekday: dict[int, list[BusinessHour]] = defaultdict(list)
    for hour in hours:
        by_weekday[hour.day_of_week].append(hour)

    local_start = window_start.replace(tzinfo=UTC).astimezone(timezone).date()
    local_end = window_end.replace(tzinfo=UTC).astimezone(timezone).date()
    candidate_day = local_start - timedelta(days=1)  # Includes Sunday hours spilling into Monday.
    result: list[Interval] = []
    while candidate_day <= local_end:
        for hour in by_weekday.get(candidate_day.weekday(), []):
            start = local_boundary(candidate_day, hour.start_time_local, timezone, is_end=False)
            end_day = candidate_day
            if hour.end_time_local <= hour.start_time_local:
                end_day += timedelta(days=1)
            end = local_boundary(end_day, hour.end_time_local, timezone, is_end=True)
            clipped_start, clipped_end = max(start, window_start), min(end, window_end)
            if clipped_start < clipped_end:
                result.append(Interval(clipped_start, clipped_end))
        candidate_day += timedelta(days=1)
    return merge_intervals(result)


def overlap_seconds(span_start: datetime, span_end: datetime, intervals: list[Interval]) -> float:
    """Calculate how many seconds of a status span fall inside open intervals."""
    return sum(
        (min(span_end, interval.end) - max(span_start, interval.start)).total_seconds()
        for interval in intervals
        if span_start < interval.end and interval.start < span_end
    )


def calculate_window(
    window_start: datetime,
    window_end: datetime,
    readings: list[Reading],
    open_intervals: list[Interval],
) -> tuple[float, float]:
    """Calculate active/inactive time using a status carry-forward interpolation.

    A poll's status applies from its timestamp until the next poll. At a reporting-window
    start with no earlier poll, the first poll in the window is backfilled to the start so
    that periodic observations cover the entire requested business interval. With no polls
    at all, the interval is conservatively reported as downtime.
    """
    open_seconds = sum((item.end - item.start).total_seconds() for item in open_intervals)
    if not open_seconds or not readings:
        return 0.0, open_seconds

    ordered = sorted(readings, key=lambda item: item.timestamp)
    previous = [reading for reading in ordered if reading.timestamp <= window_start]
    following = [reading for reading in ordered if reading.timestamp > window_start]
    state = previous[-1].status if previous else following[0].status if following else ordered[-1].status
    boundaries = [reading for reading in following if reading.timestamp < window_end]

    active_seconds = 0.0
    cursor = window_start
    for reading in boundaries:
        seconds = overlap_seconds(cursor, reading.timestamp, open_intervals)
        if state == "active":
            active_seconds += seconds
        cursor, state = reading.timestamp, reading.status

    seconds = overlap_seconds(cursor, window_end, open_intervals)
    if state == "active":
        active_seconds += seconds
    return active_seconds, open_seconds - active_seconds


def _load_readings(session: Session, start: datetime, end: datetime) -> dict[str, list[Reading]]:
    """Load weekly observations plus each store's most recent preceding observation."""
    latest_before = (
        select(StoreStatus.store_id, func.max(StoreStatus.timestamp_utc).label("timestamp"))
        .where(StoreStatus.timestamp_utc < start)
        .group_by(StoreStatus.store_id)
        .subquery()
    )
    prior = aliased(StoreStatus)
    prior_rows = session.execute(
        select(prior).join(
            latest_before,
            and_(prior.store_id == latest_before.c.store_id, prior.timestamp_utc == latest_before.c.timestamp),
        )
    ).scalars()
    current_rows = session.execute(
        select(StoreStatus).where(StoreStatus.timestamp_utc >= start, StoreStatus.timestamp_utc <= end)
    ).scalars()
    readings: dict[str, list[Reading]] = defaultdict(list)
    for status in list(prior_rows) + list(current_rows):
        readings[status.store_id].append(Reading(status.timestamp_utc, status.status))
    return readings


def generate_csv(session: Session, report: Report, output_path: Path) -> None:
    """Calculate all store metrics for one report and write its CSV artifact."""
    week_start = report.reference_time_utc - timedelta(days=7)
    readings_by_store = _load_readings(session, week_start, report.reference_time_utc)
    timezone_by_store = dict(session.execute(select(StoreTimezone.store_id, StoreTimezone.timezone_str)).all())
    default_timezone_name = get_settings().default_timezone
    ZoneInfo(default_timezone_name)
    hours_by_store: dict[str, list[BusinessHour]] = defaultdict(list)
    for hours in session.execute(select(BusinessHour)).scalars():
        hours_by_store[hours.store_id].append(hours)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(CSV_HEADER)
        for store_id in sorted(readings_by_store):
            timezone = ZoneInfo(timezone_by_store.get(store_id, default_timezone_name))
            store_hours = hours_by_store[store_id]
            row: list[str] = [store_id]
            for _name, duration, unit in WINDOWS:
                start = report.reference_time_utc - duration
                intervals = business_intervals(start, report.reference_time_utc, timezone, store_hours)
                uptime, downtime = calculate_window(start, report.reference_time_utc, readings_by_store[store_id], intervals)
                divisor = 60 if unit == "minutes" else 3600
                row.append(f"{uptime / divisor:.2f}")
                if _name == "last_week":
                    week_downtime = f"{downtime / divisor:.2f}"
                elif _name == "last_day":
                    day_downtime = f"{downtime / divisor:.2f}"
                else:
                    hour_downtime = f"{downtime / divisor:.2f}"
            row.extend([hour_downtime, day_downtime, week_downtime])
            writer.writerow(row)


def create_report(session: Session) -> Report:
    """Persist a queued report anchored to the latest imported status timestamp."""
    reference_time = session.scalar(select(func.max(StoreStatus.timestamp_utc)))
    if reference_time is None:
        raise ValueError("Cannot generate a report before status data has been ingested.")
    report = Report(
        id=str(uuid4()),
        status="Running",
        reference_time_utc=reference_time,
        created_at=utc_now_naive(),
    )
    session.add(report)
    session.commit()
    return report


def run_report(session_factory: sessionmaker[Session], report_id: str) -> None:
    """Execute a report job and persist either its completed artifact or failure state."""
    settings = get_settings()
    with session_factory() as session:
        report = session.get(Report, report_id)
        if report is None:
            return
        try:
            output_path = settings.reports_directory / f"{report.id}.csv"
            generate_csv(session, report, output_path)
            report.status = "Complete"
            report.completed_at = utc_now_naive()
            report.csv_path = str(output_path.resolve())
            session.commit()
        except Exception as error:
            session.rollback()
            failed = session.get(Report, report_id)
            if failed is not None:
                failed.status = "Failed"
                failed.error_message = str(error)[:512]
                session.commit()
            raise
