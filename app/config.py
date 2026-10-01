"""Centralized runtime configuration for the Store Monitoring service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Immutable application settings loaded from environment variables."""

    database_url: str
    reports_directory: Path
    default_timezone: str


def get_settings() -> Settings:
    """Build settings with local development defaults rooted at the project directory."""
    root = Path(__file__).resolve().parent.parent
    return Settings(
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{root / 'store_monitoring.db'}"),
        reports_directory=Path(os.getenv("REPORTS_DIRECTORY", root / "reports")),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "America/Chicago"),
    )
