"""The incident catalogue, executed.

Every scenario in `data/incidents/scenarios.yaml` is driven through the real
deterministic pipeline here -- coding, unit normalisation, plausible-range
guard, FHIR resource construction, and policy evaluation -- offline, with no
keys and no network. If `docs/incidents.md` claims a scenario produces a
critical dissolved-oxygen alert routed to the veterinary audience, that claim
fails CI when it stops being true.

The named tests below the manifest loop cover the behaviours the catalogue
argues are load-bearing, so a regression names itself rather than showing up
as an unexplained count mismatch.
"""

import csv
from pathlib import Path
from typing import Any

import pytest
import yaml

from aquafhir.coding import ReviewedCodingAgent
from aquafhir.fhir import build_resources
from aquafhir.models import Alert, MappingProposal, RawReading
from aquafhir.service import reading_from_csv_row
from aquafhir.thresholds import ThresholdPolicy

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "data" / "incidents" / "scenarios.yaml"
SCENARIOS: list[dict[str, Any]] = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))[
    "scenarios"
]
SCENARIOS_BY_ID = {scenario["id"]: scenario for scenario in SCENARIOS}


def _readings(dataset: str) -> list[RawReading]:
    with (ROOT / dataset).open(encoding="utf-8", newline="") as handle:
        return [
            reading_from_csv_row(row, {"incident_fixture": dataset, "synthetic": True})
            for row in csv.DictReader(handle)
        ]


def run_scenario(
    scenario: dict[str, Any],
    agent: ReviewedCodingAgent,
    policy: ThresholdPolicy,
) -> tuple[list[MappingProposal], list[Alert]]:
    """Propose every reading, then evaluate policy on the ones a reviewer could approve."""
    proposals = [agent.propose(reading) for reading in _readings(scenario["dataset"])]
    alerts: list[Alert] = []
    for proposal in proposals:
        if proposal.coding and proposal.has_publishable_value:
            _location, _organization, observation = build_resources(proposal)
            alerts.extend(policy.evaluate(observation))
    return proposals, alerts


def outcome(proposal: MappingProposal) -> str:
    if not proposal.coding:
        return "no_code"
    if not proposal.has_publishable_value:
        return "blocked_qty"
    return "coded"


@pytest.fixture(scope="module")
def agent() -> ReviewedCodingAgent:
    return ReviewedCodingAgent(ROOT / "config" / "coding-rules.yaml")


@pytest.fixture(scope="module")
def policy() -> ThresholdPolicy:
    return ThresholdPolicy(ROOT / "config" / "thresholds.yaml")


@pytest.fixture(scope="module")
def results(
    agent: ReviewedCodingAgent, policy: ThresholdPolicy
) -> dict[str, tuple[list[MappingProposal], list[Alert]]]:
    return {
        scenario["id"]: run_scenario(scenario, agent, policy) for scenario in SCENARIOS
    }


def scenario_case(scenario_id: str, results) -> tuple[list[MappingProposal], list[Alert]]:
    return results[scenario_id]


# -- the manifest, enforced -------------------------------------------------


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["id"])
def test_every_scenario_produces_the_documented_outcome(
    scenario: dict[str, Any], results
) -> None:
    proposals, alerts = results[scenario["id"]]
    expected = scenario["expect"]

    assert len(proposals) == scenario["rows"], (
        f"{scenario['id']}: fixture row count changed"
    )

    counted = {"coded": 0, "blocked_qty": 0, "no_code": 0}
    for proposal in proposals:
        counted[outcome(proposal)] += 1
    assert counted == {
        "coded": expected["coded"],
        "blocked_qty": expected["blocked_qty"],
        "no_code": expected["no_code"],
    }, f"{scenario['id']}: coding outcomes changed"

    fired = {(alert.rule_code, alert.severity) for alert in alerts}
    documented = {(rule["code"], rule["severity"]) for rule in expected["alerts"]}
    assert fired == documented, f"{scenario['id']}: alert set changed"

    routed = sorted({audience for alert in alerts for audience in alert.audiences})
    assert routed == sorted(expected["audiences"]), (
        f"{scenario['id']}: audience routing changed"
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["id"])
def test_no_scenario_reading_is_ever_auto_approved(
    scenario: dict[str, Any], results
) -> None:
    """The whole catalogue exists to be reviewed. Nothing in it may self-publish."""
    proposals, _alerts = results[scenario["id"]]
    assert all(proposal.requires_review for proposal in proposals)
    assert all(proposal.status.value == "pending" for proposal in proposals)
    assert all(proposal.confidence <= 0.99 for proposal in proposals)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["id"])
def test_a_blocked_quantity_can_never_be_published(
    scenario: dict[str, Any], results
) -> None:
    """`build_resources` must refuse anything the coding stage withheld."""
    proposals, _alerts = results[scenario["id"]]
    for proposal in proposals:
        if outcome(proposal) in {"blocked_qty", "no_code"}:
            with pytest.raises(ValueError):
                build_resources(proposal)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["id"])
def test_every_fixture_declares_itself_synthetic(scenario: dict[str, Any]) -> None:
    readings = _readings(scenario["dataset"])
    assert readings, f"{scenario['id']}: fixture is empty"
    assert all(reading.raw_payload.get("synthetic") for reading in readings)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["id"])
def test_referenced_fixture_files_exist(scenario: dict[str, Any]) -> None:
    assert (ROOT / scenario["dataset"]).is_file()
    if scenario.get("bulletin"):
        assert (ROOT / scenario["bulletin"]).is_file()


# -- sensor faults must not become alerts -----------------------------------


def test_a_negative_dissolved_oxygen_raises_nothing(results) -> None:
    """The regression this guard was written for.

    A failed probe reporting -5 mg/L used to be coded at 0.99 confidence and
    raise a *critical* alert routed to veterinary and water-authority.
    """
    proposals, _alerts = scenario_case("edge-cases", results)
    negative = next(item for item in proposals if item.reading.value == -5.0)
    assert negative.coding is not None, "the concept is still recognised"
    assert negative.normalized_value is None, "but the number is withheld"
    assert "plausible range" in negative.rationale
    assert negative.confidence <= 0.69


def test_a_decimal_typo_in_ph_is_withheld_not_published(results) -> None:
    proposals, _alerts = scenario_case("ajka-2010", results)
    typo = next(item for item in proposals if item.reading.value == 130.0)
    assert typo.coding is not None and typo.coding.code == "ph"
    assert typo.normalized_value is None
    assert "plausible range" in typo.rationale


@pytest.mark.parametrize("value", [-400.0, 999999.0])
def test_physically_impossible_values_are_withheld(
    value: float, results
) -> None:
    proposals, _alerts = scenario_case("edge-cases", results)
    faulty = next(item for item in proposals if item.reading.value == value)
    assert faulty.normalized_value is None


def test_an_unknown_unit_still_blocks_the_quantity_not_the_proposal(results) -> None:
    proposals, _alerts = scenario_case("edge-cases", results)
    absurd = next(
        item for item in proposals if item.reading.unit == "quarts per fortnight"
    )
    assert absurd.coding is not None, "the reviewer still sees a proposed concept"
    assert absurd.normalized_value is None
    assert "needs reviewer correction" in absurd.rationale


# -- policy boundaries ------------------------------------------------------


def test_thresholds_are_inclusive_at_the_boundary(results) -> None:
    _proposals, alerts = scenario_case("edge-cases", results)
    boundary = {
        (alert.rule_code, alert.value) for alert in alerts
    }
    assert ("dissolved-oxygen", 4.0) in boundary, "lte 4.0 must fire at exactly 4.0"
    assert ("electrical-conductivity", 2.0) in boundary, "gte 2.0 must fire at exactly 2.0"


def test_thresholds_do_not_fire_just_outside_the_boundary(results) -> None:
    _proposals, alerts = scenario_case("edge-cases", results)
    values = {alert.value for alert in alerts}
    assert 4.01 not in values
    assert 1.99 not in values


def test_two_rules_on_one_code_get_distinct_alert_ids(policy: ThresholdPolicy) -> None:
    """`ph-alkaline` and `ph-acidic` share a code; their alert ids must differ.

    They cannot both fire on one reading, but an `INSERT OR IGNORE` on a
    colliding id would silently drop the second of any pair that could.
    """
    ph_rules = [rule for rule in policy.rules if rule["code"] == "ph"]
    assert len(ph_rules) == 2
    assert {rule["id"] for rule in ph_rules} == {"ph-alkaline", "ph-acidic"}

    observation = {
        "resourceType": "Observation",
        "id": "obs-ph-collision",
        "code": {"coding": [{"code": "ph"}]},
        "valueQuantity": {"value": 13.0, "code": "[pH]"},
        "subject": {"reference": "Location/torna-kolontar"},
        "effectiveDateTime": "2010-10-04T14:00:00+00:00",
    }
    alerts = policy.evaluate(observation)
    assert len(alerts) == 1 and alerts[0].severity == "critical"
    assert len({alert.id for alert in alerts}) == len(alerts)


# -- terminology gaps are surfaced, never papered over ----------------------


GAP_CASES = [
    ("milwaukee-1993", "turbidity"),
    ("walkerton-2000", "free chlorine residual"),
    ("toledo-2014", "microcystin-LR"),
    ("baia-mare-2000", "total cyanide"),
    ("seine-2024", "enterococci"),
    ("akerselva-2011", "free chlorine residual"),
]


@pytest.mark.parametrize(("scenario_id", "parameter"), GAP_CASES)
def test_an_indicator_the_oah_ig_lacks_is_refused_not_guessed(
    scenario_id: str, parameter: str, results
) -> None:
    proposals, _alerts = scenario_case(scenario_id, results)
    gaps = [item for item in proposals if item.reading.parameter == parameter]
    assert gaps, f"{scenario_id}: fixture no longer contains {parameter!r}"
    for proposal in gaps:
        assert proposal.coding is None, (
            f"{parameter!r} was coded. If the OAH IG has since published a term "
            "for it, add the rule and update docs/incidents.md; do not map it to "
            "a neighbouring concept."
        )
        assert proposal.candidates, "the reviewer must still see the near misses"


def test_incompatible_estimators_are_not_silently_converted(results) -> None:
    """MPN and CFU are different estimators. Equating them would be the bug."""
    proposals, _alerts = scenario_case("seine-2024", results)
    mpn = next(item for item in proposals if item.reading.unit == "MPN/100mL")
    cfu = next(
        item
        for item in proposals
        if item.reading.unit == "CFU/100mL" and item.reading.value == 980
    )
    assert cfu.normalized_value == 980.0 and cfu.normalized_unit == "{cfu}/dL"
    assert mpn.coding is not None and mpn.coding.code == "coliforms"
    assert mpn.normalized_value is None, "MPN must reach a reviewer, not a factor table"


# -- the codes we do use are real -------------------------------------------


def test_every_curated_code_is_an_oah_temporary_code_system_concept(
    agent: ReviewedCodingAgent,
) -> None:
    """No invented codes, checked against the IG itself, not a transcription.

    The published code system is vendored in data/oah/ (see its README for the
    exact package build). Widening the catalog means checking the IG first,
    which is the point; see tests/test_oah_package.py for the profile bindings.
    """
    import json

    document = json.loads(
        (ROOT / "data" / "oah" / "CodeSystem-temporarySystem-oah-eu.json").read_text("utf-8")
    )
    published = {concept["code"] for concept in document["concept"]}
    assert set(agent.codes()) <= published, sorted(set(agent.codes()) - published)


def test_every_policy_rule_targets_a_code_the_catalog_can_produce(
    agent: ReviewedCodingAgent, policy: ThresholdPolicy
) -> None:
    """A rule on a code nothing can emit is dead policy, and reads as coverage."""
    catalog = set(agent.codes())
    orphans = {rule["code"] for rule in policy.rules} - catalog
    assert not orphans, f"policy rules with no matching curated code: {sorted(orphans)}"


def test_every_policy_rule_uses_a_unit_the_catalog_normalises_to(
    agent: ReviewedCodingAgent, policy: ThresholdPolicy
) -> None:
    """A rule whose unit no conversion targets can never fire. Silent dead policy."""
    for rule in policy.rules:
        catalog_rule = agent.rule_for_code(rule["code"])
        assert catalog_rule is not None
        if rule["operator"] in {"in", "not-in"}:
            # A coded rule compares value-set concepts, not units.
            allowed = {item.code for item in agent.accepted_values_for_rule(catalog_rule)}
            assert set(rule["values"]) <= allowed, (
                f"policy rule {rule.get('id', rule['code'])} lists values outside the "
                f"reviewed value set for {rule['code']}"
            )
            continue
        targets = set(catalog_rule.get("accepted_units", []))
        targets.update(
            conversion["target"]
            for conversion in catalog_rule.get("unit_conversions", {}).values()
        )
        assert rule["unit"] in targets, (
            f"policy rule {rule.get('id', rule['code'])} compares against "
            f"{rule['unit']!r}, which {rule['code']} never normalises to"
        )


def test_every_alert_audience_is_one_the_briefing_writer_knows(
    agent: ReviewedCodingAgent, policy: ThresholdPolicy
) -> None:
    from aquafhir.briefing import KNOWN_AUDIENCES

    for rule in policy.rules:
        unknown = set(rule["audiences"]) - set(KNOWN_AUDIENCES)
        assert not unknown, (
            f"policy rule {rule.get('id', rule['code'])} routes to {sorted(unknown)}, "
            "for which no advisory can ever be drafted"
        )
