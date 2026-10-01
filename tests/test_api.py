"""HTTP-level regression tests for Store Monitoring report endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import create_app
from app.models import Report

RUNNING_REPORT_ID = "11111111-1111-1111-1111-111111111111"
COMPLETE_REPORT_ID = "22222222-2222-2222-2222-222222222222"


def test_get_report_returns_running_state_for_a_known_report() -> None:
    """A persisted running report must be returned as JSON instead of raising a server error."""
    class FakeSession:
        """Minimal session substitute that returns one known report."""

        def get(self, model: type[Report], report_id: str) -> Report | None:
            """Return a running report only when the route requests the Report model."""
            if model is Report and report_id == RUNNING_REPORT_ID:
                return Report(id=RUNNING_REPORT_ID, status="Running")
            return None

    app = create_app()

    def override_get_db():
        """Provide the isolated test database session to the request handler."""
        yield FakeSession()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.get("/get_report", params={"report_id": RUNNING_REPORT_ID})

    assert response.status_code == 200
    assert response.json() == {"status": "Running", "report_id": RUNNING_REPORT_ID}


def test_complete_report_returns_csv_attachment() -> None:
    """A completed report must directly return its CSV attachment."""
    csv_path = (
        Path(__file__).resolve().parent.parent
        / "sample-output"
        / "store_monitoring_dbfea6fa-2144-4409-88b0-8e11aaf1580a.csv"
    )

    class FakeSession:
        """Minimal session substitute that returns one completed report."""

        def get(self, model: type[Report], report_id: str) -> Report | None:
            """Return a completed report with an existing CSV artifact."""
            if model is Report and report_id == COMPLETE_REPORT_ID:
                return Report(id=COMPLETE_REPORT_ID, status="Complete", csv_path=str(csv_path))
            return None

    app = create_app()

    def override_get_db():
        """Provide the completed-report session to the request handler."""
        yield FakeSession()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.get("/get_report", params={"report_id": COMPLETE_REPORT_ID})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]


def test_get_report_rejects_an_invalid_report_id() -> None:
    """The polling endpoint must reject report IDs that are not UUIDs."""
    with TestClient(create_app()) as client:
        response = client.get("/get_report", params={"report_id": "not-a-uuid"})

    assert response.status_code == 422


def test_trigger_report_rejects_a_request_body() -> None:
    """The no-input trigger endpoint must reject unexpected JSON input."""
    with TestClient(create_app()) as client:
        response = client.post("/trigger_report", json={"unexpected": "value"})

    assert response.status_code == 422
