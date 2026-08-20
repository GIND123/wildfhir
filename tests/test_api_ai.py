"""HTTP contract for the AI surfaces, including how they fail."""

import pytest
from fastapi.testclient import TestClient

from aquafhir import main
from aquafhir.config import Settings
from aquafhir.models import ReviewStatus


@pytest.fixture
def settings_without_key(monkeypatch) -> Settings:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def settings_with_key(monkeypatch) -> Settings:
    settings = Settings(_env_file=None, gemini_api_key="test-key")
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    return settings


def client_for(service) -> TestClient:
    main.app.dependency_overrides[main.get_service] = lambda: service
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main.app.dependency_overrides.clear()


def test_ai_status_reports_deterministic_only_without_a_key(service, settings_without_key):
    body = client_for(service).get("/api/v1/ai/status").json()

    assert body["enabled"] is False
    assert body["features"] == []
    assert "fully functional" in body["detail"]


def test_ai_status_lists_every_wired_feature_with_a_key(ai_service, settings_with_key):
    body = client_for(ai_service).get("/api/v1/ai/status").json()

    assert body["enabled"] is True
    assert body["provider"] == "google-gemini"
    assert set(body["features"]) == {
        "terminology-coding-copilot",
        "unstructured-intake",
        "audience-advisory-drafting",
        "grounded-situation-report",
    }
    assert body["confidence_ceiling"] < 1.0


def test_health_names_the_active_ai_mode(ai_service, settings_with_key):
    body = client_for(ai_service).get("/api/v1/health").json()

    assert body["ai_mode"] == "gemini"
    assert body["ai_model"] == settings_with_key.gemini_model


def test_intake_without_a_key_returns_503_not_500(service, settings_without_key):
    response = client_for(service).post("/api/v1/intake", json={"text": "conductivity 2350 uS/cm"})

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_an_upstream_gemini_failure_returns_502(ai_service, fake_gemini, settings_with_key):
    fake_gemini.responses = []  # FakeGemini raises GeminiError when drained

    response = client_for(ai_service).post("/api/v1/intake", json={"text": "conductivity 2350"})

    assert response.status_code == 502
    assert "Gemini upstream failure" in response.json()["detail"]


def test_replay_loads_the_synthetic_timeline_as_pending_work(service, settings_without_key):
    response = client_for(service).post("/api/v1/replay")

    assert response.status_code == 201
    proposals = response.json()
    assert len(proposals) == 5
    assert {item["status"] for item in proposals} == {ReviewStatus.PENDING.value}
    assert proposals[0]["reading"]["raw_payload"]["synthetic"] is True


def test_batch_approval_decides_each_proposal_individually(service, settings_without_key):
    client = client_for(service)
    created = client.post("/api/v1/replay").json()
    ids = [item["id"] for item in created]

    response = client.post(
        "/api/v1/proposals/approve-batch",
        json={"reviewer": "reviewer@example.org", "proposal_ids": [*ids, "does-not-exist"]},
    )
    body = response.json()

    assert response.status_code == 200
    assert len(body["approved"]) == 5
    assert body["failures"][0]["proposal_id"] == "does-not-exist"
    # Three of the five replay readings cross the demonstration policy.
    assert len(client.get("/api/v1/alerts").json()) == 3
    assert client.get("/api/v1/provenance/verify").json()["valid"] is True


def test_briefing_endpoint_rejects_an_unknown_audience(ai_service, settings_with_key):
    response = client_for(ai_service).post(
        "/api/v1/alerts/any-id/briefings", params={"audience": "press-office"}
    )

    assert response.status_code in {400, 404}


def test_openapi_documents_the_ai_endpoints(service, settings_without_key):
    paths = client_for(service).get("/openapi.json").json()["paths"]

    assert "/api/v1/intake" in paths
    assert "/api/v1/ai/situation-report" in paths
    assert "/api/v1/alerts/{alert_id}/briefings" in paths
    assert "/api/v1/proposals/approve-batch" in paths
