# Store Monitoring

A FastAPI service that imports Loop's three CSV sources into SQLite and asynchronously generates per-store uptime/downtime reports. It does not precompute results during ingestion: every trigger builds a fresh report against the latest status observation in the database.

The project structure and responsibility boundaries are documented in [Architecture](docs/architecture.md).

## Assumptions and interpolation

The data has hourly-ish observations rather than exact transition times. For a store, a poll's state is carried forward until the next poll. If a report window starts before the first available poll in that window, that first state is backfilled to the beginning of the window. This covers the complete business interval without inventing additional state changes. A store with no usable poll history is treated conservatively as inactive.

Business-hour intervals are created in each store's IANA timezone, converted to UTC, unioned to avoid double counting, and then intersected with the report windows. Multiple daily intervals and schedules crossing midnight are supported. Missing business hours mean 24/7; missing timezones mean `America/Chicago`. DST fall-back uses the earlier opening and later closing instant; spring-forward invalid wall times move to the first valid minute.

The source statement has a one-word typo (`update_last_week`). The generated CSV uses the intended, symmetric field name: `uptime_last_week(in hours)`.

## Run it

Create an environment and install the project:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Import the supplied files. The import is transactional; statuses and timezones use upserts, while business hours are replaced as a source snapshot.

```powershell
python scripts\ingest_data.py `
  --status-csv source-data\store_status.csv `
  --hours-csv source-data\menu_hours.csv `
  --timezone-csv source-data\timezones.csv
```

Start the server:

```powershell
uvicorn app.main:app --reload
```

Trigger, then poll a report:

```powershell
$report = Invoke-RestMethod -Method Post http://127.0.0.1:8000/trigger_report
Invoke-WebRequest "http://127.0.0.1:8000/get_report?report_id=$($report.report_id)" -OutFile report.csv
```

`POST /trigger_report` returns `202` and `{ "report_id": "..." }`. `GET /get_report?report_id=...` returns JSON with `Running` while work is pending. Once complete it returns the CSV attachment with `X-Report-Status: Complete`; failed jobs return JSON with `Failed` and a concise error.

## Output

The output columns are:

```text
store_id,uptime_last_hour(in minutes),uptime_last_day(in hours),uptime_last_week(in hours),downtime_last_hour(in minutes),downtime_last_day(in hours),downtime_last_week(in hours)
```

All values are fixed to two decimal places. A real output generated from the supplied CSVs is committed under `sample-output/` after running the import.

## Tests

```powershell
python -m pytest
```

The unit tests cover status interpolation, default 24/7 availability, overnight business hours, and conservative no-history handling.

## Production improvements

- Move background jobs to a durable worker queue such as Celery/RQ and store report artifacts in object storage.
- Use PostgreSQL with `COPY`/bulk upserts, source-version metadata, and incremental imports for faster large-scale refreshes.
- Add authentication, rate limits, structured metrics, tracing, and a report retention policy.
- Add property-based tests around DST transitions and integration tests against PostgreSQL.

## Demo checklist

For the requested short recording: show import completion, start Uvicorn, call `POST /trigger_report`, poll `GET /get_report`, and open the downloaded CSV. Briefly point out `app/reporting.py` for business-hours/interpolation logic and `app/ingest.py` for database ingestion.
