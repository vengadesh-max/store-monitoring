"""Pydantic response contracts exposed by the HTTP API."""

from pydantic import BaseModel


class TriggerReportResponse(BaseModel):
    """Response returned after a report job has been accepted."""

    report_id: str


class RunningReportResponse(BaseModel):
    """Response returned while a report is awaiting completion."""

    status: str
    report_id: str


class FailedReportResponse(RunningReportResponse):
    """Response returned when background report generation cannot complete."""

    detail: str
