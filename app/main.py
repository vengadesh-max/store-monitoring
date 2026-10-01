"""FastAPI composition root exposing the report trigger and polling endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import Base, SessionFactory, get_db
from app.models import Report
from app.reporting import create_report, run_report
from app.schemas import FailedReportResponse, RunningReportResponse, TriggerReportResponse


def create_app() -> FastAPI:
    """Create the HTTP application and wire routes to service-layer operations."""
    app = FastAPI(title="Store Monitoring API", version="1.0.0")

    @app.on_event("startup")
    def create_tables() -> None:
        """Create local database tables when the application process starts."""
        Base.metadata.create_all(SessionFactory.kw["bind"])

    @app.post("/trigger_report", response_model=TriggerReportResponse, status_code=202)
    def trigger_report(background_tasks: BackgroundTasks, session: Session = Depends(get_db)) -> TriggerReportResponse:
        """Create a durable report job and schedule its background calculation."""
        try:
            report = create_report(session)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        background_tasks.add_task(run_report, SessionFactory, report.id)
        return TriggerReportResponse(report_id=report.id)

    @app.get("/get_report", response_model=RunningReportResponse | FailedReportResponse)
    def get_report(report_id: str, session: Session = Depends(get_db)):
        """Return job state until complete, then stream the generated CSV artifact."""
        report = session.get(Report, report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Unknown report_id")
        if report.status == "Running":
            return RunningReportResponse(status="Running", report_id=report.id)
        if report.status == "Failed":
            return FailedReportResponse(status="Failed", report_id=report.id, detail=report.error_message or "Unknown error")
        if not report.csv_path or not Path(report.csv_path).is_file():
            raise HTTPException(status_code=500, detail="Completed report file is unavailable")
        return FileResponse(
            report.csv_path,
            media_type="text/csv",
            filename=f"store_monitoring_{report.id}.csv",
            headers={"X-Report-Status": "Complete", "X-Report-Id": report.id},
        )

    return app


app = create_app()
