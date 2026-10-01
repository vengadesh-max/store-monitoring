"""Command-line entry point for importing the supplied Store Monitoring CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.db import Base, SessionFactory
from app.ingest import ingest_all


def main() -> None:
    """Parse source paths, initialize the schema, and run one transactional import."""
    parser = argparse.ArgumentParser(description="Import Store Monitoring CSV sources into the database.")
    parser.add_argument("--status-csv", type=Path, required=True)
    parser.add_argument("--hours-csv", type=Path, required=True)
    parser.add_argument("--timezone-csv", type=Path, required=True)
    args = parser.parse_args()

    Base.metadata.create_all(SessionFactory.kw["bind"])
    with SessionFactory() as session:
        counts = ingest_all(session, args.status_csv, args.hours_csv, args.timezone_csv)
    print("Imported " + ", ".join(f"{name}={count}" for name, count in counts.items()))


if __name__ == "__main__":
    main()
