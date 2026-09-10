"""Live connectors, with the HTTP hop removed.

The recorded payloads below are verbatim shapes from the real Hub'Eau and
Copernicus catalogue APIs, so parsing, unit preservation, the
below-quantification-limit guard, and the provenance entry all run for real.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from aquafhir.coding import ReviewedCodingAgent
from aquafhir.connectors import (
    ConnectorError,
    ConnectorUnavailableError,
    CopernicusClient,
    HubEauClient,
    load_connector_config,
)
from aquafhir.gemini import GeminiClient
from aquafhir.models import ConnectorPullRequest, ReviewDecision
from tests.conftest import _build

HUBEAU_ROWS = [
    {"code_station": "05163000", "libelle_station": "La Garonne dans Toulouse (St-Pierre)",
     "date_prelevement": "2024-11-19", "heure_prelevement": "10:06:00", "code_parametre": "1303",
     "libelle_parametre": "Conductivité à 25°C", "resultat": 277.0, "symbole_unite": "µS/cm",
     "code_unite": "147", "code_fraction": "23", "libelle_fraction": "Eau brute",
     "code_remarque": "1", "mnemo_remarque": "Résultat > seuil de quantification et < au seuil de saturation",  # noqa: E501
     "code_prelevement": "A123", "nom_producteur": "AEAG", "longitude": 1.435571267, "latitude": 43.601939515},  # noqa: E501
    {"code_station": "05163000", "libelle_station": "La Garonne dans Toulouse (St-Pierre)",
     "date_prelevement": "2024-11-19", "heure_prelevement": "10:06:00", "code_parametre": "1311",
     "libelle_parametre": "Oxygène dissous", "resultat": 11.5, "symbole_unite": "mg(O2)/L",
     "code_unite": "175", "code_fraction": "23", "libelle_fraction": "Eau brute",
     "code_remarque": "1", "mnemo_remarque": "Résultat > seuil de quantification",
     "code_prelevement": "A123", "nom_producteur": "AEAG", "longitude": 1.435571267, "latitude": 43.601939515},  # noqa: E501
    {"code_station": "05163000", "libelle_station": "La Garonne dans Toulouse (St-Pierre)",
     "date_prelevement": "2024-11-19", "heure_prelevement": "10:06:00", "code_parametre": "1340",
     "libelle_parametre": "Nitrates", "resultat": 3.9, "symbole_unite": "mg(NO3)/L",
     "code_unite": "162", "code_fraction": "3", "libelle_fraction": "Phase aqueuse",
     "code_remarque": "1", "mnemo_remarque": "Résultat > seuil de quantification",
     "code_prelevement": "A123", "nom_producteur": "AEAG", "longitude": 1.435571267, "latitude": 43.601939515},  # noqa: E501
    {"code_station": "05163000", "libelle_station": "La Garonne dans Toulouse (St-Pierre)",
     "date_prelevement": "2024-11-19", "heure_prelevement": "10:06:00", "code_parametre": "1382",
     "libelle_parametre": "Plomb", "resultat": 0.1, "symbole_unite": "µg/L",
     "code_unite": "133", "code_fraction": "23", "libelle_fraction": "Eau brute",
     "code_remarque": "10", "mnemo_remarque": "Résultat < au seuil de quantification",
     "code_prelevement": "A123", "nom_producteur": "AEAG", "longitude": 1.435571267, "latitude": 43.601939515},  # noqa: E501
    {"code_station": "05163000", "libelle_station": "La Garonne dans Toulouse (St-Pierre)",
     "date_prelevement": "2024-11-19", "heure_prelevement": "10:06:00", "code_parametre": "1449",
     "libelle_parametre": "Escherichia coli (E. coli)", "resultat": 179.0, "symbole_unite": "n/(100mL)",  # noqa: E501
     "code_unite": "226", "code_fraction": "23", "libelle_fraction": "Eau brute",
     "code_remarque": "1", "mnemo_remarque": "Résultat > seuil de quantification",
     "code_prelevement": "A123", "nom_producteur": "AEAG", "longitude": 1.435571267, "latitude": 43.601939515},  # noqa: E501
]

SCENES = {
    "value": [
        {"Id": "83cd10f2-e227-4866-a1f2-54903b7a7d5c",
         "Name": "S2A_MSIL2A_20260908T104651_N0512_R051_T31TCJ_20260908T191911.SAFE",
         "Online": True, "ContentDate": {"Start": "2026-09-08T10:46:51.024000Z", "End": "2026-09-08T10:46:51.024000Z"},  # noqa: E501
         "Attributes": [{"Name": "cloudCover", "Value": 21.368848}, {"Name": "productType", "Value": "S2MSI2A"},  # noqa: E501
                        {"Name": "tileId", "Value": "31TCJ"}]},
        {"Id": "aaaa", "Name": "S2B_MSIL2A_20260901T104619_N0512_R051_T31TCJ_20260901T132404.SAFE",
         "Online": True, "ContentDate": {"Start": "2026-09-01T10:46:19.024000Z"},
         "Attributes": [{"Name": "cloudCover", "Value": 7.357162}, {"Name": "productType", "Value": "S2MSI2A"},  # noqa: E501
                        {"Name": "tileId", "Value": "31TCJ"}]},
    ]
}

STATISTICS = {
    "status": "OK",
    "data": [
        {"interval": {"from": "2026-09-08T00:00:00Z", "to": "2026-09-09T00:00:00Z"},
         "outputs": {"ndci": {"bands": {"B0": {"stats": {"min": -0.12, "max": 0.51, "mean": 0.4123,
                                                         "stDev": 0.08, "sampleCount": 3240, "noDataCount": 40}}}}}},  # noqa: E501
        {"interval": {"from": "2026-09-05T00:00:00Z", "to": "2026-09-06T00:00:00Z"},
         "outputs": {"ndci": {"bands": {"B0": {"stats": {"min": 0, "max": 0, "mean": 0,
                                                         "stDev": 0, "sampleCount": 3240, "noDataCount": 3240}}}}}},  # noqa: E501
    ],
}


class FakeHubEau(HubEauClient):
    def __init__(self, rows: list[dict[str, Any]] | Exception, **kwargs) -> None:
        super().__init__(max_retries=0, **kwargs)
        self.rows = rows
        self.calls: list[dict[str, str]] = []

    def _get_with_retries(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        self.calls.append(params)
        if isinstance(self.rows, Exception):
            raise self.rows
        return {"count": len(self.rows), "data": self.rows}


class FakeCopernicus(CopernicusClient):
    def __init__(self, *, scenes=SCENES, statistics=STATISTICS, **kwargs) -> None:
        super().__init__(max_retries=0, **kwargs)
        self.scene_payload = scenes
        self.statistics_payload = statistics
        self.calls: list[tuple[str, Any]] = []

    def _get_with_retries(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        self.calls.append(("catalogue", params))
        return self.scene_payload

    def _post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        self.calls.append(("token", data))
        return {"access_token": "t0k", "expires_in": 600}

    def _post_statistics(self, body: dict[str, Any], token: str) -> dict[str, Any]:
        self.calls.append(("statistics", {"token": token, "body": body}))
        return self.statistics_payload


CONFIG = load_connector_config("config/connectors.yaml")


def connector_service(tmp_path, hubeau=None, copernicus=None):
    return _build(
        tmp_path, GeminiClient(api_key="", model="gemini-test"),
        ReviewedCodingAgent("config/coding-rules.yaml"),
        hubeau=hubeau, copernicus=copernicus, connector_config=CONFIG,
    )


# -- Hub'Eau --------------------------------------------------------------------


def test_hubeau_rows_become_readings_with_the_french_label_and_unit_verbatim(tmp_path) -> None:
    service = connector_service(tmp_path, hubeau=FakeHubEau(HUBEAU_ROWS))
    result = service.pull_hubeau(ConnectorPullRequest(stations=["05163000"]))
    assert result.connector == "hubeau" and result.fetched == 5
    labels = {p.reading.parameter: p for p in result.proposals}
    assert set(labels) == {"Conductivité à 25°C", "Oxygène dissous", "Nitrates", "Escherichia coli (E. coli)"}  # noqa: E501
    conductivity = labels["Conductivité à 25°C"]
    assert conductivity.reading.unit == "µS/cm"            # micro sign, as the API wrote it
    assert conductivity.reading.site_code == "hubeau-05163000"
    assert conductivity.reading.raw_payload["synthetic"] is False
    assert conductivity.reading.raw_payload["pilot_city"] == "Toulouse"
    assert "code_prelevement=A123" in str(conductivity.reading.evidence_url)


def test_hubeau_readings_are_coded_by_the_ordinary_catalog(tmp_path) -> None:
    service = connector_service(tmp_path, hubeau=FakeHubEau(HUBEAU_ROWS))
    result = service.pull_hubeau(ConnectorPullRequest())
    by_label = {p.reading.parameter: p for p in result.proposals}
    assert by_label["Conductivité à 25°C"].coding.code == "electrical-conductivity"
    assert by_label["Conductivité à 25°C"].normalized_value == pytest.approx(0.277)
    assert by_label["Conductivité à 25°C"].normalized_unit == "mS/cm"
    assert by_label["Oxygène dissous"].normalized_value == pytest.approx(11.5)
    assert by_label["Nitrates"].coding.code == "nitrate"
    assert by_label["Nitrates"].normalized_value == pytest.approx(3.9)
    # E. coli in n/(100mL): MPN or CFU depends on the method, so the connector
    # does not guess and the quantity is withheld for a reviewer.
    ecoli = by_label["Escherichia coli (E. coli)"]
    assert ecoli.coding.code == "coliforms"
    assert ecoli.normalized_value is None
    assert all(p.status.value == "pending" for p in result.proposals)


def test_a_below_quantification_limit_result_is_skipped_and_explained(tmp_path) -> None:
    service = connector_service(tmp_path, hubeau=FakeHubEau(HUBEAU_ROWS))
    result = service.pull_hubeau(ConnectorPullRequest())
    assert len(result.skipped) == 1
    assert "Plomb" in result.skipped[0] and "limit, not a measurement" in result.skipped[0]
    assert not any(p.reading.parameter == "Plomb" for p in result.proposals)


def test_a_pull_is_hash_chained_with_its_query(tmp_path) -> None:
    hub = FakeHubEau(HUBEAU_ROWS)
    service = connector_service(tmp_path, hubeau=hub)
    result = service.pull_hubeau(ConnectorPullRequest(stations=["05163000"], days=30, limit=10))
    entry = next(e for e in service.repository.list_provenance(100) if e.event_type == "connector-pull")  # noqa: E501
    assert entry.entity_id == result.request_hash
    assert entry.payload["connector"] == "hubeau"
    assert entry.payload["query"]["stations"] == ["05163000"]
    assert entry.payload["fetched"] == 5 and entry.payload["skipped"] == 1 and entry.payload["queued"] == 4  # noqa: E501
    assert set(entry.payload["proposal_ids"]) == {p.id for p in result.proposals}
    assert hub.calls[0]["code_station"] == "05163000"
    assert hub.calls[0]["size"] == "10"
    assert service.repository.verify_chain().valid


def test_a_live_reading_still_needs_a_reviewer(tmp_path) -> None:
    service = connector_service(tmp_path, hubeau=FakeHubEau(HUBEAU_ROWS))
    result = service.pull_hubeau(ConnectorPullRequest())
    proposal = next(p for p in result.proposals if p.coding.code == "electrical-conductivity")
    assert proposal.requires_review
    approved = service.approve(proposal.id, ReviewDecision(reviewer="r@x"))
    assert approved.observation["valueQuantity"]["code"] == "mS/cm"
    assert approved.observation["subject"]["reference"] == "Location/hubeau-05163000"


def test_an_unknown_station_is_refused(tmp_path) -> None:
    service = connector_service(tmp_path, hubeau=FakeHubEau(HUBEAU_ROWS))
    with pytest.raises(ConnectorUnavailableError, match="station"):
        service.pull_hubeau(ConnectorPullRequest(stations=["nope"]))


def test_a_disabled_hubeau_says_so(tmp_path) -> None:
    service = connector_service(tmp_path, hubeau=FakeHubEau(HUBEAU_ROWS, enabled=False))
    with pytest.raises(ConnectorUnavailableError, match="HUBEAU_ENABLED"):
        service.pull_hubeau(ConnectorPullRequest())
    assert service.connector_statuses()[0].live is False


def test_an_upstream_failure_is_a_connector_error_not_a_500(tmp_path) -> None:
    service = connector_service(tmp_path, hubeau=FakeHubEau(ConnectorError("hubeau answered 503")))
    with pytest.raises(ConnectorError):
        service.pull_hubeau(ConnectorPullRequest())
    assert service.repository.list_proposals() == []


# -- Copernicus ---------------------------------------------------------------------


def test_scene_listing_is_keyless_and_parses_the_catalogue(tmp_path) -> None:
    cds = FakeCopernicus()
    service = connector_service(tmp_path, copernicus=cds)
    site, scenes, url = service.sentinel_scenes("garonne-toulouse", days=30, max_cloud=40)
    assert site["pilot_city"] == "Toulouse"
    assert [s.tile_id for s in scenes] == ["31TCJ", "31TCJ"]
    assert scenes[0].cloud_cover == pytest.approx(21.368848)
    assert scenes[0].sensed_at == datetime(2026, 9, 8, 10, 46, 51, 24000, tzinfo=UTC)
    assert scenes[0].catalogue_url.endswith("Products(83cd10f2-e227-4866-a1f2-54903b7a7d5c)")
    params = cds.calls[0][1]
    assert "S2MSI2A" in params["$filter"] and "cloudCover" in params["$filter"]
    assert "POINT(1.43560 43.60190)" in params["$filter"]
    assert "Products?" in url and "SENTINEL-2" in httpx.URL(url).params["$filter"]


def test_ndci_needs_credentials_and_says_which(tmp_path) -> None:
    service = connector_service(tmp_path, copernicus=FakeCopernicus())
    with pytest.raises(ConnectorUnavailableError, match="CDSE_CLIENT_ID"):
        service.pull_sentinel2(ConnectorPullRequest(site_code="garonne-toulouse"))
    status = service.connector_statuses()[1]
    assert status.auth == "credentials-required" and status.live is True


def test_ndci_intervals_become_satellite_readings_citing_their_scene(tmp_path) -> None:
    cds = FakeCopernicus(client_id="id", client_secret="secret")
    service = connector_service(tmp_path, copernicus=cds)
    result = service.pull_sentinel2(ConnectorPullRequest(site_code="garonne-toulouse", days=30))
    # The all-no-data day is not a reading: no water pixels means no index.
    assert result.fetched == 1 and len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.reading.source_type.value == "satellite"
    assert proposal.coding.code == "ndci"
    assert proposal.normalized_value == pytest.approx(0.4123)
    assert proposal.reading.raw_payload["scene"].startswith("S2A_MSIL2A_20260908")
    assert proposal.reading.raw_payload["statistics"]["water_pixels"] == 3200
    assert "Products(83cd10f2" in str(proposal.reading.evidence_url)
    kinds = [call[0] for call in cds.calls]
    assert kinds == ["catalogue", "token", "statistics"]
    body = cds.calls[2][1]["body"]
    assert body["input"]["bounds"]["bbox"] == [1.42, 43.57, 1.445, 43.615]
    assert body["input"]["data"][0]["type"] == "sentinel-2-l2a"
    assert "B05" in body["aggregation"]["evalscript"]
    # The NDCI rule fires once a reviewer approves, exactly like a replayed reading.
    approved = service.approve(proposal.id, ReviewDecision(reviewer="r@x"))
    assert [a.rule_code for a in approved.alerts] == ["ndci"]


def test_an_unknown_sentinel_site_is_a_404_shape(tmp_path) -> None:
    from aquafhir.service import ProposalNotFoundError

    service = connector_service(tmp_path, copernicus=FakeCopernicus())
    with pytest.raises(ProposalNotFoundError):
        service.sentinel_scenes("atlantis")


# -- the HTTP surface ---------------------------------------------------------


def test_the_connector_endpoints_degrade_cleanly_without_network(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from aquafhir import main

    with TestClient(main.app) as client:
        statuses = client.get("/api/v1/connectors").json()
        assert [s["name"] for s in statuses] == ["hubeau", "sentinel2"]
        assert statuses[0]["auth"] == "keyless"
        service = client.app.state.service
        service.hubeau = FakeHubEau(HUBEAU_ROWS)
        service.copernicus = FakeCopernicus()
        pulled = client.post("/api/v1/connectors/hubeau/pull", json={"stations": ["05163000"]})
        assert pulled.status_code == 201
        assert pulled.json()["fetched"] == 5 and len(pulled.json()["proposals"]) == 4
        scenes = client.get("/api/v1/connectors/sentinel2/scenes", params={"site_code": "garonne-toulouse"})  # noqa: E501
        assert scenes.status_code == 200 and len(scenes.json()["scenes"]) == 2
        missing = client.get("/api/v1/connectors/sentinel2/scenes", params={"site_code": "atlantis"})  # noqa: E501
        assert missing.status_code == 404
        ndci = client.post("/api/v1/connectors/sentinel2/pull", json={"site_code": "garonne-toulouse"})  # noqa: E501
        assert ndci.status_code == 503 and "CDSE_CLIENT_ID" in ndci.json()["detail"]
        service.hubeau = FakeHubEau(ConnectorError("hubeau answered 503"))
        broken = client.post("/api/v1/connectors/hubeau/pull", json={})
        assert broken.status_code == 502 and broken.json()["error_code"] == "connector-upstream-error"  # noqa: E501
