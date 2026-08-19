from fastapi.testclient import TestClient

from aquafhir.main import app, get_service


def test_dashboard_and_review_api(service):
    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)
    payload = {
        "source_id": "agency-api-test",
        "source_type": "agency",
        "parameter": "EC",
        "value": 2.35,
        "unit": "mS/cm",
        "observed_at": "2022-07-27T08:00:00Z",
        "site_code": "oder-kostrzyn",
        "site_name": "Oder at Kostrzyn",
        "latitude": 52.5887,
        "longitude": 14.6495,
    }
    try:
        assert client.get("/").status_code == 200
        created = client.post("/api/v1/proposals", json=payload)
        assert created.status_code == 201
        proposal_id = created.json()["id"]

        approved = client.post(
            f"/api/v1/proposals/{proposal_id}/approve",
            json={"reviewer": "api-reviewer"},
        )
        assert approved.status_code == 200
        assert approved.json()["proposal"]["status"] == "approved"
        assert len(client.get("/api/v1/alerts").json()) == 1
    finally:
        app.dependency_overrides.clear()


def test_quantity_override_must_be_complete(service):
    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/proposals/unused/approve",
            json={"reviewer": "api-reviewer", "normalized_unit": "mS/cm"},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()

