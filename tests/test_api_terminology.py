"""HTTP contract for the UMLS terminology crosswalk, including how it fails."""

import pytest
from fastapi.testclient import TestClient

from aquafhir import main
from aquafhir.config import Settings


@pytest.fixture
def settings_without_umls_key(monkeypatch) -> Settings:
    monkeypatch.delenv("UMLS_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def settings_with_umls_key(monkeypatch) -> Settings:
    settings = Settings(_env_file=None, umls_api_key="test-key")
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    return settings


def client_for(service) -> TestClient:
    main.app.dependency_overrides[main.get_service] = lambda: service
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main.app.dependency_overrides.clear()


def test_terminology_status_is_off_without_a_key(service, settings_without_umls_key):
    body = client_for(service).get("/api/v1/terminology/status").json()

    assert body["enabled"] is False
    assert body["vocabularies"] == []
    assert "not set" in body["detail"]


def test_terminology_status_lists_vocabularies_with_a_key(umls_service, settings_with_umls_key):
    body = client_for(umls_service).get("/api/v1/terminology/status").json()

    assert body["enabled"] is True
    assert body["provider"] == "nlm-umls-uts"
    assert set(body["vocabularies"]) == {"LNC", "SNOMEDCT_US"}


def test_health_names_the_terminology_crosswalk_mode(umls_service, settings_with_umls_key):
    body = client_for(umls_service).get("/api/v1/health").json()

    assert body["terminology_crosswalk"] == "umls"


def test_suggestions_without_a_key_return_503_not_500(service, settings_without_umls_key):
    client = client_for(service)
    proposal = client.post(
        "/api/v1/proposals",
        json={
            "source_id": "agency-test",
            "source_type": "agency",
            "parameter": "dissolved oxygen",
            "value": 6.1,
            "unit": "mg/L",
            "observed_at": "2022-07-27T08:00:00Z",
            "site_code": "oder-kostrzyn",
            "site_name": "Oder at Kostrzyn",
            "latitude": 52.5887,
            "longitude": 14.6495,
        },
    ).json()

    response = client.get(f"/api/v1/proposals/{proposal['id']}/terminology-suggestions")

    assert response.status_code == 503
    assert "UMLS_API_KEY" in response.json()["detail"]


def test_suggestions_for_an_unknown_proposal_are_404(umls_service, settings_with_umls_key):
    response = client_for(umls_service).get(
        "/api/v1/proposals/does-not-exist/terminology-suggestions"
    )

    assert response.status_code == 404


def test_suggestions_surface_a_real_loinc_candidate(
    umls_service, fake_umls, settings_with_umls_key
):
    client = client_for(umls_service)
    fake_umls.responses = [
        {
            "result": {
                "results": [
                    {"ui": "11556-8", "rootSource": "LNC", "name": "Dissolved oxygen"},
                ]
            }
        }
    ]
    proposal = client.post(
        "/api/v1/proposals",
        json={
            "source_id": "agency-test",
            "source_type": "agency",
            "parameter": "dissolved oxygen",
            "value": 6.1,
            "unit": "mg/L",
            "observed_at": "2022-07-27T08:00:00Z",
            "site_code": "oder-kostrzyn",
            "site_name": "Oder at Kostrzyn",
            "latitude": 52.5887,
            "longitude": 14.6495,
        },
    ).json()

    response = client.get(f"/api/v1/proposals/{proposal['id']}/terminology-suggestions")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["system"] == "http://loinc.org"
    assert body[0]["code"] == "11556-8"


def test_reviewer_can_attach_a_suggested_secondary_coding_at_approval(
    umls_service, settings_with_umls_key
):
    client = client_for(umls_service)
    proposal = client.post(
        "/api/v1/proposals",
        json={
            "source_id": "agency-test",
            "source_type": "agency",
            "parameter": "dissolved oxygen",
            "value": 6.1,
            "unit": "mg/L",
            "observed_at": "2022-07-27T08:00:00Z",
            "site_code": "oder-kostrzyn",
            "site_name": "Oder at Kostrzyn",
            "latitude": 52.5887,
            "longitude": 14.6495,
        },
    ).json()

    approved = client.post(
        f"/api/v1/proposals/{proposal['id']}/approve",
        json={
            "reviewer": "api-reviewer",
            "secondary_coding": {
                "system": "http://loinc.org",
                "code": "11556-8",
                "display": "Dissolved oxygen",
            },
        },
    )

    assert approved.status_code == 200
    codings = approved.json()["observation"]["code"]["coding"]
    assert len(codings) == 2
    assert codings[1] == {
        "system": "http://loinc.org",
        "code": "11556-8",
        "display": "Dissolved oxygen",
    }


def test_openapi_documents_the_terminology_endpoints(service, settings_without_umls_key):
    paths = client_for(service).get("/openapi.json").json()["paths"]

    assert "/api/v1/terminology/status" in paths
    assert "/api/v1/proposals/{proposal_id}/terminology-suggestions" in paths
