import sqlite3
from datetime import UTC, datetime

import pytest

from aquafhir.fhir import OAH_LOCATION_PROFILE, OAH_OBSERVATION_PROFILE, FhirClient
from aquafhir.models import RawReading, ReviewDecision, SourceType
from aquafhir.service import InvalidReviewStateError


def high_conductivity_reading() -> RawReading:
    return RawReading(
        source_id="pl-agency-001",
        source_type=SourceType.AGENCY,
        parameter="electrical conductivity",
        value=2.35,
        unit="mS/cm",
        observed_at=datetime(2022, 7, 27, 8, tzinfo=UTC),
        site_code="oder-kostrzyn",
        site_name="Oder at Kostrzyn",
        latitude=52.5887,
        longitude=14.6495,
    )


def test_approval_builds_oah_resources_and_alert(service):
    proposal = service.propose(high_conductivity_reading())
    result = service.approve(proposal.id, ReviewDecision(reviewer="reviewer@example.org"))

    # Dry run states plainly that nothing was published and nothing validated.
    assert result.fhir_response["transaction"]["mode"] == "dry-run"
    assert result.fhir_response["transaction"]["published"] is False
    assert result.fhir_response["validation"]["observation"]["mode"] == "skipped"
    assert result.fhir_response["validation"]["observation"]["validated"] is False
    assert result.observation["meta"]["profile"] == [OAH_OBSERVATION_PROFILE]
    assert result.observation["subject"]["reference"] == "Location/oder-kostrzyn"
    assert result.observation["performer"]
    assert result.observation["valueQuantity"]["system"] == "http://unitsofmeasure.org"
    assert len(result.alerts) == 1
    assert result.alerts[0].severity == "high"


def test_location_shape_matches_required_oah_fields(service, monkeypatch):
    proposal = service.propose(high_conductivity_reading())
    captured = {}

    def capture(bundle):
        captured["bundle"] = bundle
        return {"mode": "captured"}

    monkeypatch.setattr(service.fhir_client, "publish", capture)
    service.approve(proposal.id, ReviewDecision(reviewer="reviewer"))
    location = captured["bundle"]["entry"][0]["resource"]

    assert location["meta"]["profile"] == [OAH_LOCATION_PROFILE]
    assert location["identifier"]
    assert location["mode"] == "instance"
    assert location["type"][0]["coding"][0]["code"] == "420531007"
    assert set(location["position"]) == {"latitude", "longitude"}


def test_review_decision_is_immutable(service):
    proposal = service.propose(high_conductivity_reading())
    decision = ReviewDecision(reviewer="reviewer")
    service.approve(proposal.id, decision)

    with pytest.raises(InvalidReviewStateError):
        service.approve(proposal.id, decision)


def test_provenance_chain_detects_tampering(service):
    proposal = service.propose(high_conductivity_reading())
    service.approve(proposal.id, ReviewDecision(reviewer="reviewer"))
    assert service.repository.verify_chain().valid is True

    with sqlite3.connect(service.repository.path) as connection:
        connection.execute(
            "UPDATE provenance SET payload = ? WHERE sequence = 1", ('{"tampered":true}',)
        )

    verification = service.repository.verify_chain()
    assert verification.valid is False
    assert verification.first_invalid_sequence == 1


def test_r4_subscription_uses_empty_notification():
    client = FhirClient("http://unused.test/fhir", write_enabled=False, timeout=1)
    result = client.install_subscription(
        "https://bridge.example/api/v1/webhooks/fhir", "secret"
    )

    channel = result["resource"]["channel"]
    assert channel["type"] == "rest-hook"
    assert "payload" not in channel


def test_subscription_poll_is_idempotent_for_alert_storage(service, monkeypatch):
    proposal = service.propose(high_conductivity_reading())
    result = service.approve(proposal.id, ReviewDecision(reviewer="reviewer"))
    events_before = len(service.repository.list_provenance())
    monkeypatch.setattr(
        service.fhir_client,
        "fetch_recent_observations",
        lambda since: [result.observation],
    )

    processed, alerts = service.process_subscription_notification()

    assert processed == 1
    assert len(alerts) == 1
    assert len(service.repository.list_alerts()) == 1
    assert len(service.repository.list_provenance()) == events_before
    assert service.repository.get_cursor("fhir-last-sync") is not None
