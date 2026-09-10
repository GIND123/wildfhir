"""The same guarantees over HTTP, where a hand-rolled request can bypass the UI."""

import pytest
from fastapi.testclient import TestClient

from aquafhir import main
from aquafhir.config import Settings

READING = {
    "source_id": "pl-agency-001", "source_type": "agency", "parameter": "EC",
    "value": 2444, "unit": "uS/cm", "observed_at": "2022-07-27T08:00:00Z",
    "site_code": "oder-kostrzyn", "site_name": "Oder at Kostrzyn",
    "latitude": 52.5887, "longitude": 14.6495,
}


@pytest.fixture
def settings(monkeypatch) -> Settings:
    value = Settings(_env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: value)
    return value


@pytest.fixture
def client(service, settings) -> TestClient:
    main.app.dependency_overrides[main.get_service] = lambda: service
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def make(client: TestClient) -> str:
    return client.post("/api/v1/proposals", json=READING).json()["id"]


def test_the_reported_bug_is_a_422_over_http(client, service) -> None:
    pid = make(client)
    response = client.post(
        f"/api/v1/proposals/{pid}/approve",
        json={
            "reviewer": "r@x", "normalized_value": 2319.0,
            "normalized_unit": "mS/cm", "correction_reason": "typo",
        },
    )
    assert response.status_code == 422
    assert "plausible range" in response.json()["detail"]
    assert client.get("/api/v1/alerts").json() == []


def test_an_invented_code_is_a_422_over_http(client) -> None:
    pid = make(client)
    response = client.post(
        f"/api/v1/proposals/{pid}/approve",
        json={
            "reviewer": "r@x",
            "coding": {"system": "http://evil.example", "code": "made-up", "display": "F"},
        },
    )
    assert response.status_code == 422
    assert "curated catalog" in response.json()["detail"]


def test_an_unaccepted_unit_is_a_422_over_http(client) -> None:
    pid = make(client)
    response = client.post(
        f"/api/v1/proposals/{pid}/approve",
        json={
            "reviewer": "r@x", "normalized_value": 2444.0,
            "normalized_unit": "uS/cm", "correction_reason": "keep source unit",
        },
    )
    assert response.status_code == 422
    assert "not an accepted unit" in response.json()["detail"]


def test_a_correction_without_a_reason_is_rejected_by_the_schema(client) -> None:
    pid = make(client)
    response = client.post(
        f"/api/v1/proposals/{pid}/approve",
        json={"reviewer": "r@x", "normalized_value": 3.1, "normalized_unit": "mS/cm"},
    )
    assert response.status_code == 422


def test_the_normalization_endpoint_returns_the_formula(client) -> None:
    pid = make(client)
    body = client.get(
        f"/api/v1/proposals/{pid}/normalization",
        params={"code": "electrical-conductivity"},
    ).json()
    assert body["status"] == "ok"
    assert body["normalized_value"] == pytest.approx(2.444)
    assert body["formula"] == "2444 uS/cm × 0.001 = 2.444 mS/cm"
    assert body["accepted_units"] == ["mS/cm"]


def test_a_normal_approval_still_succeeds_and_publishes_the_derived_value(client) -> None:
    pid = make(client)
    body = client.post(f"/api/v1/proposals/{pid}/approve", json={"reviewer": "r@x"}).json()
    assert body["observation"]["valueQuantity"]["value"] == pytest.approx(2.444)


def test_the_approved_observation_survives_a_reload(client) -> None:
    """The console must be able to show what was published after a refresh."""
    pid = make(client)
    client.post(f"/api/v1/proposals/{pid}/approve", json={"reviewer": "r@x"})
    stored = client.get(f"/api/v1/proposals/{pid}/observation").json()
    assert stored["observation"]["valueQuantity"]["value"] == pytest.approx(2.444)
    assert stored["fhir_response"]["transaction"]["mode"] == "dry-run"


def test_a_pending_proposal_has_no_stored_observation(client) -> None:
    pid = make(client)
    assert client.get(f"/api/v1/proposals/{pid}/observation").status_code == 404


def test_dry_run_never_claims_publication_or_validation(client) -> None:
    pid = make(client)
    body = client.post(f"/api/v1/proposals/{pid}/approve", json={"reviewer": "r@x"}).json()
    receipt = body["fhir_response"]
    assert receipt["transaction"]["published"] is False
    assert receipt["validation"]["observation"]["validated"] is False
    assert receipt["validation"]["observation"]["mode"] == "skipped"
    # The words are allowed to appear as field names; what must never appear is
    # an affirmative claim that either happened.
    assert "nothing was sent" in receipt["transaction"]["detail"]
    assert "skipped" in receipt["validation"]["observation"]["detail"]
    assert "profile" in receipt["validation"]["observation"]


def test_batch_approval_still_works_and_stays_authoritative(client, service) -> None:
    ids = [make(client) for _ in range(2)]
    body = client.post(
        "/api/v1/proposals/approve-batch",
        json={"reviewer": "r@x", "proposal_ids": ids},
    ).json()
    assert len(body["approved"]) == 2
    assert all(
        item["observation"]["valueQuantity"]["value"] == pytest.approx(2.444)
        for item in body["approved"]
    )


def test_a_duplicate_reading_is_flagged_on_the_proposal(client) -> None:
    first = make(client)
    second = client.post("/api/v1/proposals", json=READING).json()
    assert second["duplicate_of"] == first


def test_openapi_documents_the_new_endpoints(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/proposals/{proposal_id}/normalization" in paths
    assert "/api/v1/proposals/{proposal_id}/observation" in paths


def test_no_code_proposal_can_carry_a_reviewed_unit_suggestion(client) -> None:
    body = client.post(
        "/api/v1/proposals",
        json={**READING, "parameter": "where", "unit": "uS/cm"},
    ).json()
    assert body["coding"] is None
    assert body["candidates"][0]["code"] == "electrical-conductivity"
    assert body["candidates"][0]["origin"] == "reviewed-unit"


def test_no_code_proposal_still_cannot_be_approved_without_a_selected_code(client) -> None:
    pid = client.post(
        "/api/v1/proposals",
        json={**READING, "parameter": "where", "unit": "uS/cm"},
    ).json()["id"]
    response = client.post(f"/api/v1/proposals/{pid}/approve", json={"reviewer": "r@x"})
    assert response.status_code == 409
    assert "Select a code" in response.json()["detail"]


def test_ai_status_separates_configured_from_healthy(client) -> None:
    body = client.get("/api/v1/ai/status").json()
    assert body["configured"] is False
    assert body["health"] == "disabled"
    assert body["last_call"] is None
