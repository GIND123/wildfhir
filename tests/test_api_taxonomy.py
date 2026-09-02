"""HTTP contract for the GBIF biodiversity crosswalk, including how it fails."""

import pytest
from fastapi.testclient import TestClient

from aquafhir import main
from aquafhir.config import Settings
from aquafhir.gbif import GBIF_SYSTEM
from aquafhir.models import RawReading
from tests.fakes import BrokenGbif

TROUT = {
    "usageKey": 2401664, "scientificName": "Salmo trutta Linnaeus, 1758",
    "canonicalName": "Salmo trutta", "rank": "SPECIES", "status": "ACCEPTED",
    "confidence": 99, "matchType": "EXACT", "kingdom": "Animalia",
}
REFUSAL = {"matchType": "NONE", "confidence": 100, "synonym": False}


@pytest.fixture
def settings(monkeypatch) -> Settings:
    monkeypatch.delenv("UMLS_API_KEY", raising=False)
    value = Settings(_env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: value)
    return value


def client_for(service) -> TestClient:
    main.app.dependency_overrides[main.get_service] = lambda: service
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main.app.dependency_overrides.clear()


def propose(service, parameter: str, unit: str = "{count}"):
    return service.propose(
        RawReading(
            source_id="oslo-vav", source_type="agency", parameter=parameter, value=12,
            unit=unit, observed_at="2011-03-09T09:00:00Z", site_code="akerselva-vaterland",
            site_name="Akerselva at Vaterland", latitude=59.9110, longitude=10.7590,
        )
    )


def test_suggestions_surface_a_real_gbif_taxon(taxon_service, settings):
    service = taxon_service([REFUSAL, TROUT])
    proposal = propose(service, "Salmo trutta count")

    body = client_for(service).get(f"/api/v1/proposals/{proposal.id}/taxon-suggestions").json()

    assert len(body) == 1
    assert body[0]["code"] == "2401664"
    assert body[0]["system"] == GBIF_SYSTEM
    assert body[0]["vocabulary"] == "GBIF"


def test_a_chemical_parameter_returns_an_empty_list_not_an_error(taxon_service, settings):
    """An empty list is the honest answer, and must not read as a failure."""
    service = taxon_service([REFUSAL, REFUSAL, REFUSAL])
    proposal = propose(service, "dissolved oxygen", unit="mg/L")

    response = client_for(service).get(f"/api/v1/proposals/{proposal.id}/taxon-suggestions")

    assert response.status_code == 200
    assert response.json() == []


def test_suggestions_for_an_unknown_proposal_are_404(taxon_service, settings):
    service = taxon_service([TROUT])
    response = client_for(service).get("/api/v1/proposals/does-not-exist/taxon-suggestions")
    assert response.status_code == 404


def test_the_endpoint_returns_503_when_the_source_is_switched_off(service, settings):
    """Without a GBIF client the feature is absent, not broken."""
    proposal = propose(service, "fish count")
    response = client_for(service).get(f"/api/v1/proposals/{proposal.id}/taxon-suggestions")
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


def test_an_upstream_gbif_failure_returns_502(tmp_path, curated_agent, settings):
    """A lookup that broke must not be reported to a reviewer as "no organism"."""
    from aquafhir.gemini import GeminiClient
    from tests.conftest import _build

    service = _build(
        tmp_path, GeminiClient(api_key="", model="gemini-test"), curated_agent,
        gbif=BrokenGbif(),
    )
    proposal = propose(service, "Salmo trutta count")

    response = client_for(service).get(f"/api/v1/proposals/{proposal.id}/taxon-suggestions")

    assert response.status_code == 502
    assert "GBIF upstream failure" in response.json()["detail"]


def test_terminology_status_reports_the_biodiversity_source(taxon_service, settings):
    body = client_for(taxon_service([])).get("/api/v1/terminology/status").json()
    assert "gbif" in body["sources"]
    assert "organism" in body["detail"]


def test_openapi_documents_the_taxon_endpoint(taxon_service, settings):
    spec = client_for(taxon_service([])).get("/openapi.json").json()
    assert "/api/v1/proposals/{proposal_id}/taxon-suggestions" in spec["paths"]
