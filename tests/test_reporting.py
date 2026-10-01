"""Unit tests for business-hours expansion and status interpolation edge cases."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.models import BusinessHour
from app.reporting import Interval, Reading, business_intervals, calculate_window


def test_carry_forward_interpolation_is_limited_to_business_hours() -> None:
    """The first observation backfills a window but only during the store's open interval."""
    start = datetime(2024, 1, 1, 9, 0)
    end = datetime(2024, 1, 1, 12, 0)
    intervals = [Interval(start, end)]
    readings = [
        Reading(datetime(2024, 1, 1, 10, 14), "active"),
        Reading(datetime(2024, 1, 1, 11, 15), "inactive"),
    ]

    uptime, downtime = calculate_window(start, end, readings, intervals)

    assert uptime == 135 * 60  # The first poll backfills 09:00 through 11:15.
    assert downtime == 45 * 60


def test_missing_hours_means_open_24_hours() -> None:
    """A store without business-hours rows must be treated as open for the full window."""
    start = datetime(2024, 1, 1, 0, 0)
    end = datetime(2024, 1, 2, 0, 0)

    assert business_intervals(start, end, ZoneInfo("America/Chicago"), []) == [Interval(start, end)]


def test_overnight_hours_are_included_from_the_previous_local_day() -> None:
    """Hours that cross midnight remain visible in the following day's report window."""
    timezone = ZoneInfo("UTC")
    hour = BusinessHour(store_id="store", day_of_week=6, start_time_local=time(22), end_time_local=time(2))

    intervals = business_intervals(
        datetime(2024, 1, 8, 0, 0),  # Monday
        datetime(2024, 1, 8, 3, 0),
        timezone,
        [hour],
    )

    assert intervals == [Interval(datetime(2024, 1, 8, 0, 0), datetime(2024, 1, 8, 2, 0))]


def test_unknown_poll_history_is_conservative_downtime() -> None:
    """No status information should produce downtime rather than unearned uptime."""
    start = datetime(2024, 1, 1, 9, 0)
    end = datetime(2024, 1, 1, 10, 0)

    assert calculate_window(start, end, [], [Interval(start, end)]) == (0.0, 3600.0)
