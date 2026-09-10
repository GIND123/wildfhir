"""The catalog against the IG it claims to implement.

The IG package is vendored in data/oah/ at an exact build. These checks make
the profile bindings executable: a human-leg rule must be a member of the
value set bound to observation-health-measure-oah, an environmental rule must
not be, and every coded value must be a real concept.
"""

import json
from pathlib import Path

import pytest

from aquafhir.coding import ReviewedCodingAgent
from aquafhir.fhir import OAH_HEALTH_MEASURE_PROFILE, OAH_OBSERVATION_PROFILE
from aquafhir.models import OneHealthLeg

ROOT = Path(__file__).parents[1]
OAH = ROOT / "data" / "oah"


def _json(name: str) -> dict:
    return json.loads((OAH / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def agent() -> ReviewedCodingAgent:
    return ReviewedCodingAgent(ROOT / "config" / "coding-rules.yaml")


@pytest.fixture(scope="module")
def code_system() -> set[str]:
    return {concept["code"] for concept in _json("CodeSystem-temporarySystem-oah-eu.json")["concept"]}  # noqa: E501


@pytest.fixture(scope="module")
def health_value_set() -> set[str]:
    document = _json("ValueSet-health-indicators-oah-vs.json")
    return {
        concept["code"]
        for include in document["compose"]["include"]
        for concept in include.get("concept", [])
    }


def test_the_vendored_code_system_is_the_build_the_readme_names() -> None:
    document = _json("CodeSystem-temporarySystem-oah-eu.json")
    assert document["url"] == "http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu"
    assert document["version"] == "0.1.0-ci-build"
    assert len(document["concept"]) == document["count"] == 185


def test_every_catalog_code_is_published(agent, code_system) -> None:
    missing = set(agent.codes()) - code_system
    assert not missing, sorted(missing)


def test_the_catalog_system_uri_is_the_ig_code_system(agent) -> None:
    assert agent.system == _json("CodeSystem-temporarySystem-oah-eu.json")["url"]


def test_human_leg_rules_are_bound_to_the_health_measure_value_set(agent, health_value_set) -> None:
    """observation-health-measure-oah binds `code` to health-indicators-oah-vs."""
    human = {rule["code"] for rule in agent.rules if agent.leg_for_rule(rule) is OneHealthLeg.HUMAN}
    assert human, "the human leg is empty"
    assert human <= health_value_set, sorted(human - health_value_set)


def test_environmental_and_animal_rules_are_outside_the_health_value_set(agent, health_value_set) -> None:  # noqa: E501
    """observation-indicators-oah binds `code` to the complement of that set."""
    others = {rule["code"] for rule in agent.rules if agent.leg_for_rule(rule) is not OneHealthLeg.HUMAN}  # noqa: E501
    assert not others & health_value_set, sorted(others & health_value_set)


def test_every_coded_value_is_a_published_concept(agent, code_system) -> None:
    for rule in agent.rules:
        for item in agent.accepted_values_for_rule(rule):
            assert item.code in code_system, f"{rule['code']}: value {item.code!r} is not in the IG"


def test_coded_values_come_from_the_ig_value_set(agent) -> None:
    document = _json("ValueSet-macrophytes-indicator-value-oah-vs.json")
    allowed = {c["code"] for inc in document["compose"]["include"] for c in inc.get("concept", [])}
    assert allowed == {"absent", "present", "extensive"}
    for rule in agent.rules:
        values = {item.code for item in agent.accepted_values_for_rule(rule)}
        assert values <= allowed, f"{rule['code']}: {sorted(values - allowed)}"


def test_the_two_profiles_are_the_ig_profiles() -> None:
    health = _json("StructureDefinition-observation-health-measure-oah.json")
    indicators = _json("StructureDefinition-observation-indicators-oah.json")
    assert health["url"] == OAH_HEALTH_MEASURE_PROFILE
    assert indicators["url"] == OAH_OBSERVATION_PROFILE

    def snapshot(sd, path):
        return next(el for el in sd["snapshot"]["element"] if el["path"] == path)

    # Both profiles take a Quantity or a CodeableConcept value, and a Location subject.
    for sd in (health, indicators):
        kinds = {t["code"] for t in snapshot(sd, "Observation.value[x]")["type"]}
        assert kinds == {"Quantity", "CodeableConcept"}
        subject = snapshot(sd, "Observation.subject")
        assert subject["min"] == 1
        assert any(
            "location-oah" in profile
            for t in subject["type"]
            for profile in t.get("targetProfile", [])
        )
    # The health profile binds code to the health value set; the other excludes it.
    assert snapshot(health, "Observation.code")["binding"]["valueSet"].endswith(
        "health-indicators-oah-vs"
    )
    assert snapshot(indicators, "Observation.code")["binding"]["valueSet"].endswith(
        "oah-indicators-no-health-oah-vs"
    )
