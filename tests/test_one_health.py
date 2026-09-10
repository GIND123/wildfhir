"""The One Health loop, closed: human measures on the same Location as water.

Havelock North 2016 is the fixture: sheep faeces, rain, an unchlorinated bore,
5,500 ill. The water readings sit on `brookvale-bore-1`. The district health
board's campylobacteriosis rate is published through the IG's *second*
profile, observation-health-measure-oah, against that same Location, so one
FHIR search returns both legs of the pathway.
"""

import csv
from pathlib import Path

import pytest

from aquafhir.fhir import (
    OAH_HEALTH_MEASURE_PROFILE,
    OAH_OBSERVATION_PROFILE,
    ONE_HEALTH_LEG_TAG_SYSTEM,
    build_resources,
)
from aquafhir.models import Coding, OneHealthLeg, RawReading, ReviewDecision
from aquafhir.service import ApprovalValidationError, reading_from_csv_row

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "data" / "incidents" / "havelock-north-2016.csv"


def reading(parameter: str, value: float, unit: str) -> RawReading:
    return RawReading(
        source_id="hawkes-bay-dhb", source_type="agency", parameter=parameter,
        value=value, unit=unit, observed_at="2016-08-15T00:00:00Z",
        site_code="brookvale-bore-1", site_name="Brookvale Road bore field",
        latitude=-39.6667, longitude=176.8833,
    )


def test_a_human_measure_is_published_through_the_health_measure_profile(service) -> None:
    proposal = service.propose(reading("campylobacteriosis", 7143, "{cases}/100000"))
    assert proposal.coding.code == "campylobacter"
    assert proposal.leg is OneHealthLeg.HUMAN
    result = service.approve(proposal.id, ReviewDecision(reviewer="epi@hbdhb"))
    observation = result.observation
    assert observation["meta"]["profile"] == [OAH_HEALTH_MEASURE_PROFILE]
    assert observation["subject"]["reference"] == "Location/brookvale-bore-1"
    assert observation["valueQuantity"] == {
        "value": 7143.0, "unit": "{cases}/100000",
        "system": "http://unitsofmeasure.org", "code": "{cases}/100000",
    }
    assert {"system": ONE_HEALTH_LEG_TAG_SYSTEM, "code": "human"} in observation["meta"]["tag"]
    # The profile validation call names the human profile, not the environmental one.
    assert result.fhir_response["validation"]["observation"]["profile"] == OAH_HEALTH_MEASURE_PROFILE  # noqa: E501


def test_both_legs_land_on_the_same_location(service) -> None:
    water = service.approve(
        service.propose(reading("faecal coliforms", 940, "CFU/100mL")).id,
        ReviewDecision(reviewer="lab@hbrc"),
    )
    human = service.approve(
        service.propose(reading("campylobacteriosis", 7143, "{cases}/100000")).id,
        ReviewDecision(reviewer="epi@hbdhb"),
    )
    assert water.observation["subject"] == human.observation["subject"]
    assert water.observation["meta"]["profile"] == [OAH_OBSERVATION_PROFILE]
    assert human.observation["meta"]["profile"] == [OAH_HEALTH_MEASURE_PROFILE]
    legs = {
        tag["code"]
        for item in (water, human)
        for tag in item.observation["meta"]["tag"]
        if tag["system"] == ONE_HEALTH_LEG_TAG_SYSTEM
    }
    assert legs == {"environmental", "human"}


def test_the_human_rule_routes_to_all_three_audiences(service) -> None:
    result = service.approve(
        service.propose(reading("campylobacteriosis", 7143, "{cases}/100000")).id,
        ReviewDecision(reviewer="epi@hbdhb"),
    )
    assert [alert.severity for alert in result.alerts] == ["critical"]
    assert set(result.alerts[0].audiences) == {"public-health", "veterinary", "water-authority"}
    assert result.alerts[0].unit == "{cases}/100000"


def test_a_percentage_of_the_population_converts_to_a_rate(service) -> None:
    proposal = service.propose(reading("acute gastrointestinal illness", 39.3, "%"))
    assert proposal.coding.code == "gastrointestinal"
    assert proposal.normalized_unit == "{cases}/100000"
    assert proposal.normalized_value == pytest.approx(39300.0)


def test_a_raw_case_count_is_withheld_without_a_denominator(service) -> None:
    """1000 cases of what population? No reviewed factor exists, so no number."""
    proposal = service.propose(reading("campylobacter notified cases", 1000, "cases"))
    assert proposal.coding.code == "campylobacter"
    assert proposal.normalized_value is None
    with pytest.raises(ApprovalValidationError, match="expert correction"):
        service.approve(proposal.id, ReviewDecision(reviewer="epi@hbdhb"))
    # A person who knows the population supplies the rate, with a reason.
    result = service.approve(
        proposal.id,
        ReviewDecision(
            reviewer="epi@hbdhb", normalized_value=7143.0, normalized_unit="{cases}/100000",
            correction_reason="Havelock North population 14,000 at the 2013 census",
        ),
    )
    assert result.observation["valueQuantity"]["value"] == pytest.approx(7143.0)


def test_the_leg_follows_the_code_a_reviewer_chooses(service) -> None:
    """Overriding to a human code at approval must switch the profile too."""
    proposal = service.propose(reading("gastro-enteritis notifications", 500, "{cases}/100000"))
    result = service.approve(
        proposal.id,
        ReviewDecision(
            reviewer="epi@hbdhb",
            coding=Coding(system="ignored", code="gastrointestinal", display="ignored"),
        ),
    )
    assert result.proposal.leg is OneHealthLeg.HUMAN
    assert result.observation["meta"]["profile"] == [OAH_HEALTH_MEASURE_PROFILE]


def test_an_animal_indicator_is_tagged_but_uses_the_indicators_profile(service) -> None:
    proposal = service.propose(reading("dead fish", 340, "{count}"))
    assert proposal.leg is OneHealthLeg.ANIMAL
    _location, _org, observation = build_resources(proposal)
    assert observation["meta"]["profile"] == [OAH_OBSERVATION_PROFILE]
    assert {"system": ONE_HEALTH_LEG_TAG_SYSTEM, "code": "animal"} in observation["meta"]["tag"]


def test_the_havelock_fixture_carries_three_human_rows_on_the_bore_location() -> None:
    with FIXTURE.open(encoding="utf-8", newline="") as handle:
        rows = [reading_from_csv_row(row, {"synthetic": True}) for row in csv.DictReader(handle)]
    human = [row for row in rows if row.source_id == "hawkes-bay-dhb"]
    water = [row for row in rows if row.source_id != "hawkes-bay-dhb"]
    assert len(human) == 4
    assert {row.site_code for row in human} == {"brookvale-bore-1"}
    assert "brookvale-bore-1" in {row.site_code for row in water}
