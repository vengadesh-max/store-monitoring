"""SQLAlchemy entities representing imported source data and generated reports."""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import DateTime, Index, Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StoreStatus(Base):
    """A timestamped active or inactive observation for one store."""
    __tablename__ = "store_statuses"
    __table_args__ = (
        UniqueConstraint("store_id", "timestamp_utc", name="uq_store_status_timestamp"),
        Index("ix_status_store_timestamp", "store_id", "timestamp_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False)


class BusinessHour(Base):
    """One local business-hours interval for a store and weekday."""
    __tablename__ = "business_hours"
    __table_args__ = (Index("ix_hours_store_weekday", "store_id", "day_of_week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_local: Mapped[time] = mapped_column(Time, nullable=False)
    end_time_local: Mapped[time] = mapped_column(Time, nullable=False)


class StoreTimezone(Base):
    """The IANA timezone assigned to a store."""
    __tablename__ = "store_timezones"

    store_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timezone_str: Mapped[str] = mapped_column(String(64), nullable=False)


class Report(Base):
    """The durable state and artifact location of an asynchronously generated report."""
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_time_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    csv_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
