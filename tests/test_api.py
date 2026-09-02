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



def test_integrations_masks_secrets_and_reports_wiring(service):
    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)
    try:
        body = client.get("/api/v1/integrations").json()
        assert set(body) >= {"gemini", "umls", "loinc_table", "fhir", "webhook", "policy", "coding"}
        # A fingerprint is never the key: either absent or first/last four only.
        for block in (body["gemini"], body["umls"]):
            fingerprint = block["key_fingerprint"]
            assert fingerprint is None or ("\u2026" in fingerprint and len(fingerprint) == 9)
        assert body["fhir"]["write_mode"] in {"enabled", "dry-run"}
        assert body["policy"]["id"] == service.thresholds.policy_id
        assert body["coding"]["codes"] > 0
    finally:
        app.dependency_overrides.clear()


def test_coding_catalog_lists_curated_codes(service):
    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)
    try:
        body = client.get("/api/v1/coding/catalog").json()
        codes = {item["code"] for item in body["codes"]}
        assert {"electrical-conductivity", "dissolved-oxygen", "ph"} <= codes
        conductivity = next(
            item for item in body["codes"] if item["code"] == "electrical-conductivity"
        )
        assert "mS/cm" in conductivity["accepted_units"]
        assert "uS/cm" in conductivity["unit_conversions"]
    finally:
        app.dependency_overrides.clear()
