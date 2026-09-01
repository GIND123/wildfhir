"""Malformed-input regression tests.

Two surfaces here are not under this service's control: the JSON a source
POSTs, and the Observation a FHIR server pushes down a rest-hook
Subscription. Neither may produce a 500 or an unpublishable resource.
"""

import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aquafhir import main
from aquafhir.fhir import build_resources, fhir_id
from aquafhir.models import RawReading, ReviewDecision
from aquafhir.thresholds import ThresholdPolicy


@pytest.fixture
def client(service):
    """The real app, wired to the offline deterministic service."""
    main.app.dependency_overrides[main.get_service] = lambda: service
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def _observation(**overrides):
    resource = {
        "resourceType": "Observation",
        "id": "obs-1",
        "code": {"coding": [{"code": "dissolved-oxygen"}]},
        "valueQuantity": {"value": 2.0, "code": "mg/L"},
        "subject": {"reference": "Location/oder-kostrzyn"},
        "effectiveDateTime": "2022-07-27T08:00:00Z",
    }
    resource.update(overrides)
    return resource


# -- the policy engine never raises on a resource it cannot read -----------


def test_wellformed_observation_still_alerts(policy: ThresholdPolicy) -> None:
    alerts = policy.evaluate(_observation())
    assert len(alerts) == 1
    assert alerts[0].observation_id == "obs-1"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"valueQuantity": {"value": None, "code": "mg/L"}}, id="null-value"),
        pytest.param({"valueQuantity": {"value": "abc", "code": "mg/L"}}, id="string-value"),
        pytest.param({"valueQuantity": {"value": True, "code": "mg/L"}}, id="bool-value"),
        pytest.param({"valueQuantity": {"value": 2.0}}, id="no-unit-code"),
        pytest.param({"valueQuantity": None}, id="null-quantity"),
        pytest.param({"valueQuantity": []}, id="quantity-wrong-type"),
        pytest.param({"code": None}, id="null-code"),
        pytest.param({"code": {"coding": {"code": "x"}}}, id="coding-not-a-list"),
        pytest.param({"code": {"coding": []}}, id="empty-coding"),
        pytest.param({"code": {"coding": [None]}}, id="null-coding-entry"),
        pytest.param({"effectiveDateTime": "not-a-date"}, id="unparseable-date"),
        pytest.param({"effectiveDateTime": None}, id="null-date"),
    ],
)
def test_unreadable_observation_is_skipped_not_raised(
    policy: ThresholdPolicy, overrides: dict
) -> None:
    resource = _observation(**overrides)
    if "id" not in overrides:
        assert policy.evaluate(resource) == []


@pytest.mark.parametrize(
    "overrides", [{"subject": None}, {"subject": {}}, {"subject": "Location/x"}]
)
def test_unusable_subject_falls_back_to_unknown_site(
    policy: ThresholdPolicy, overrides: dict
) -> None:
    """A missing subject is not a reason to drop an alert -- only to label it."""
    alerts = policy.evaluate(_observation(**overrides))
    assert len(alerts) == 1
    assert alerts[0].site_code == "unknown"


def test_missing_id_is_skipped(policy: ThresholdPolicy) -> None:
    resource = _observation()
    del resource["id"]
    assert policy.evaluate(resource) == []


def test_missing_effective_date_is_skipped(policy: ThresholdPolicy) -> None:
    resource = _observation()
    del resource["effectiveDateTime"]
    assert policy.evaluate(resource) == []


@pytest.mark.parametrize("literal", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_value_never_alerts(policy: ThresholdPolicy, literal: float) -> None:
    """-inf would otherwise satisfy every `lte` rule and raise a phantom alert."""
    assert policy.evaluate(_observation(valueQuantity={"value": literal, "code": "mg/L"})) == []


@pytest.mark.parametrize("partial", ["2022", "2022-07", "2022-07-27"])
def test_fhir_partial_dates_are_accepted(policy: ThresholdPolicy, partial: str) -> None:
    """FHIR `dateTime` permits YYYY and YYYY-MM, not only full instants."""
    alerts = policy.evaluate(_observation(effectiveDateTime=partial))
    assert len(alerts) == 1
    assert alerts[0].observed_at.year == 2022


# -- non-finite quantities cannot enter the pipeline at all ---------------


def _reading(value: float) -> dict:
    return {
        "source_id": "a",
        "source_type": "agency",
        "parameter": "dissolved oxygen",
        "value": value,
        "unit": "mg/L",
        "observed_at": "2022-07-27T08:00:00Z",
        "site_code": "s",
        "site_name": "S",
        "latitude": 52.0,
        "longitude": 14.0,
    }


@pytest.mark.parametrize("literal", [float("nan"), float("inf"), float("-inf")])
def test_raw_reading_rejects_non_finite(literal: float) -> None:
    with pytest.raises(ValidationError):
        RawReading.model_validate(_reading(literal))


@pytest.mark.parametrize("literal", [float("nan"), float("inf")])
def test_reviewer_cannot_override_with_non_finite(literal: float) -> None:
    with pytest.raises(ValidationError):
        ReviewDecision(reviewer="r@e.org", normalized_value=literal, normalized_unit="mg/L")


def test_finite_value_still_accepted() -> None:
    assert RawReading.model_validate(_reading(3.6)).value == 3.6


def test_published_quantity_is_always_a_real_number(pending_proposal) -> None:
    """A JSON-null valueQuantity.value would be an unpublishable Observation."""
    _, _, observation = build_resources(pending_proposal)
    value = observation["valueQuantity"]["value"]
    assert isinstance(value, int | float)
    assert math.isfinite(value)


# -- FHIR ids stay distinct ------------------------------------------------


def test_legal_ids_pass_through_unchanged() -> None:
    assert fhir_id("oder-kostrzyn") == "oder-kostrzyn"
    assert fhir_id("pl-agency-001") == "pl-agency-001"


def test_ids_needing_normalisation_do_not_collide() -> None:
    """'Oder at Kostrzyn' and 'Oder/at/Kostrzyn' both normalise identically."""
    assert fhir_id("Oder at Kostrzyn") != fhir_id("Oder/at/Kostrzyn")


def test_overlong_ids_do_not_collide_after_truncation() -> None:
    assert fhir_id("x" * 80 + "-alpha") != fhir_id("x" * 80 + "-beta")


@pytest.mark.parametrize(
    "value", ["Oder at Kostrzyn", "x" * 200, "", "MÜNCHEN", "s'; DROP TABLE proposals;--"]
)
def test_every_generated_id_is_a_legal_fhir_id(value: str) -> None:
    import re

    assert re.fullmatch(r"[A-Za-z0-9\-.]{1,64}", fhir_id(value))


# -- a 422 must render even when the rejected input is not JSON-representable


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("field", ["value", "latitude", "longitude"])
def test_non_finite_input_returns_422_not_500(client, field: str, literal: str) -> None:
    """FastAPI echoes the bad input into the 422 body; NaN there would 500."""
    numbers = {"value": "3.6", "latitude": "52.0", "longitude": "14.0"} | {field: literal}
    body = (
        '{"source_id":"a","source_type":"agency","parameter":"dissolved oxygen",'
        f'"value":{numbers["value"]},"unit":"mg/L",'
        '"observed_at":"2022-07-27T08:00:00Z","site_code":"s","site_name":"S",'
        f'"latitude":{numbers["latitude"]},"longitude":{numbers["longitude"]}}}'
    )
    response = client.post(
        "/api/v1/proposals", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]


def test_ordinary_validation_errors_still_report_the_field(client) -> None:
    response = client.post("/api/v1/proposals", json={})
    assert response.status_code == 422
    fields = {tuple(item["loc"]) for item in response.json()["detail"]}
    assert ("body", "source_id") in fields
