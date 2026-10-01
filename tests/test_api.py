"""HTTP-level regression tests for Store Monitoring report endpoints."""

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import create_app
from app.models import Report


def test_get_report_returns_running_state_for_a_known_report() -> None:
    """A persisted running report must be returned as JSON instead of raising a server error."""
    class FakeSession:
        """Minimal session substitute that returns one known report."""

        def get(self, model: type[Report], report_id: str) -> Report | None:
            """Return a running report only when the route requests the Report model."""
            if model is Report and report_id == "report-1":
                return Report(id="report-1", status="Running")
            return None

    app = create_app()

    def override_get_db():
        """Provide the isolated test database session to the request handler."""
        yield FakeSession()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.get("/get_report", params={"report_id": "report-1"})

    assert response.status_code == 200
    assert response.json() == {"status": "Running", "report_id": "report-1"}
