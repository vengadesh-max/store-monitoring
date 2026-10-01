# Architecture Context

## Purpose

This service imports operational store data and creates a downloadable report on demand. The import path only persists raw observations and configuration; it does not calculate metrics. The report path reads the current database state and uses the newest poll timestamp as its reference point.

## Layers

| Location | Responsibility |
| --- | --- |
| `app/main.py` | HTTP composition root and endpoint behavior. |
| `app/schemas.py` | Stable API response contracts. |
| `app/reporting.py` | Report service: business-hour expansion, interpolation, aggregation, and CSV output. |
| `app/ingest.py` | Input validation and batched persistence of source CSV files. |
| `app/models.py` | Database entities and indexes. |
| `app/db.py` | Engine and session lifecycle. |
| `app/config.py` | Environment-backed runtime settings. |
| `scripts/ingest_data.py` | One-purpose command-line import entry point. |
| `tests/` | Isolated unit tests; production code contains no test fixtures. |

## Main Flow

1. `scripts/ingest_data.py` validates and imports the three source CSVs in one transaction.
2. `POST /trigger_report` stores a `Running` report record using the latest known status timestamp.
3. The background job calls the reporting service, loads one week of polls plus each store's prior poll, and writes a CSV.
4. `GET /get_report` returns `Running`, `Failed`, or the completed CSV attachment.

## Calculation Policy

The reporting service represents time as naive UTC datetimes internally. It expands each store's local business schedule into UTC intervals with explicit daylight-saving handling, merges overlaps, and intersects those intervals with status spans.

A status applies from its poll timestamp until the next poll. When a requested window starts before its first in-window poll, that first state backfills the leading interval. A store without any usable observation is counted as inactive. This makes uptime plus downtime equal all eligible business time.

## Design Choices

The code uses a layered service design: HTTP handlers do not contain reporting rules, ingestion does not generate reports, and database models do not implement business calculations. This keeps the interpolation algorithm independently testable and makes a future switch from FastAPI background tasks to a durable queue localized to the job runner boundary.
