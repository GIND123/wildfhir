"""Coded indicators: the value is a word from a reviewed set, never a number.

The OneAquaHealth app records foam, macrophytes and the ordinal assessments as
words. The IG models them as CodeableConcept values from
macrophytes-indicator-value-oah-vs (absent / present / extensive). Everything
here pins one edge of the rule that a word is published exactly as a concept
of that set or not at all.
"""

import pytest

from aquafhir.models import Coding, RawReading, ReviewDecision
from aquafhir.service import ApprovalValidationError


def coded(parameter: str, word: str, source_type: str = "citizen") -> RawReading:
    return RawReading(
        source_id="oah-app-coimbra", source_type=source_type, parameter=parameter,
        coded_value=word, observed_at="2026-05-04T09:30:00Z",
        site_code="ribeira-de-coselhas", site_name="Ribeira de Coselhas at Coimbra",
        latitude=40.219, longitude=-8.423,
    )


def numeric(parameter: str, value: float, unit: str) -> RawReading:
    return RawReading(
        source_id="oah-app-coimbra", source_type="citizen", parameter=parameter,
        value=value, unit=unit, observed_at="2026-05-04T09:30:00Z",
        site_code="ribeira-de-coselhas", site_name="Ribeira de Coselhas at Coimbra",
        latitude=40.219, longitude=-8.423,
    )


# -- the reading model -------------------------------------------------------


def test_a_reading_needs_exactly_one_kind_of_value() -> None:
    with pytest.raises(ValueError, match="either a numeric value or a coded_value"):
        RawReading(
            source_id="s", source_type="citizen", parameter="foam",
            observed_at="2026-05-04T09:30:00Z", site_code="x", site_name="X",
            latitude=0, longitude=0,
        )
    with pytest.raises(ValueError, match="not both"):
        RawReading(
            source_id="s", source_type="citizen", parameter="foam", value=1, unit="1",
            coded_value="present", observed_at="2026-05-04T09:30:00Z",
            site_code="x", site_name="X", latitude=0, longitude=0,
        )
    with pytest.raises(ValueError, match="unit"):
        RawReading(
            source_id="s", source_type="citizen", parameter="foam", value=1,
            observed_at="2026-05-04T09:30:00Z", site_code="x", site_name="X",
            latitude=0, longitude=0,
        )


# -- resolution ------------------------------------------------------------


def test_a_word_in_the_value_set_resolves_to_its_concept(service) -> None:
    proposal = service.propose(coded("foam", "present"))
    assert proposal.coding.code == "foam"
    assert proposal.normalized_coding == Coding(
        system=service.catalog.system, code="present", display="Present"
    )
    assert proposal.normalized_value is None
    assert proposal.has_publishable_value


def test_a_reviewed_alias_resolves_too(service) -> None:
    proposal = service.propose(coded("macroinvertebrates", "none"))
    assert proposal.coding.code == "macroinvertebreates"
    assert proposal.normalized_coding.code == "absent"


def test_an_unlisted_word_is_withheld_not_rounded(service) -> None:
    proposal = service.propose(coded("foam", "kinda foamy"))
    assert proposal.coding.code == "foam"
    assert proposal.normalized_coding is None
    assert "not in the reviewed value set" in proposal.rationale
    assert proposal.confidence <= 0.69
    with pytest.raises(ApprovalValidationError, match="reviewed values"):
        service.approve(proposal.id, ReviewDecision(reviewer="r@x"))


def test_a_number_for_a_coded_indicator_is_withheld(service) -> None:
    proposal = service.propose(numeric("foam", 2, "mg/L"))
    assert proposal.coding.code == "foam"
    assert proposal.normalized_value is None
    assert "coded value" in proposal.rationale
    preview = service.normalization_preview(proposal.id, "foam")
    assert preview.status == "kind-mismatch"


def test_a_word_for_a_quantity_indicator_is_withheld(service) -> None:
    proposal = service.propose(coded("dissolved oxygen", "low"))
    assert proposal.coding.code == "dissolved-oxygen"
    assert proposal.normalized_coding is None
    preview = service.normalization_preview(proposal.id, "dissolved-oxygen")
    assert preview.status == "kind-mismatch"
    assert preview.value_kind == "coded"


def test_an_indicator_may_take_either_kind(service) -> None:
    count = service.propose(numeric("benthic macroinvertebrates", 42, "{count}"))
    word = service.propose(coded("benthic macroinvertebrates", "abundant"))
    assert count.normalized_value == 42 and count.normalized_unit == "{count}"
    assert word.normalized_coding.code == "extensive"


# -- publication -------------------------------------------------------------


def test_a_coded_value_publishes_as_a_codeable_concept(service) -> None:
    proposal = service.propose(coded("foam", "present"))
    result = service.approve(proposal.id, ReviewDecision(reviewer="r@x"))
    observation = result.observation
    assert "valueQuantity" not in observation
    assert observation["valueCodeableConcept"] == {
        "coding": [{"system": service.catalog.system, "code": "present", "display": "Present"}],
        "text": "Present",
    }
    assert observation["code"]["coding"][0]["code"] == "foam"
    assert any("Source reported the coded value 'present'" in n["text"] for n in observation["note"])  # noqa: E501


def test_a_coded_rule_fires_on_a_coded_value(service) -> None:
    result = service.approve(
        service.propose(coded("foam", "present")).id, ReviewDecision(reviewer="r@x")
    )
    assert len(result.alerts) == 1
    alert = result.alerts[0]
    assert alert.rule_code == "foam" and alert.severity == "moderate"
    assert alert.value is None and alert.unit == "" and alert.value_code == "present"
    assert alert.audiences == ["water-authority"]


def test_an_absent_coded_value_does_not_fire_the_present_rule(service) -> None:
    result = service.approve(
        service.propose(coded("foam", "none")).id, ReviewDecision(reviewer="r@x")
    )
    assert result.alerts == []


def test_a_coded_rule_never_reads_a_quantity(policy) -> None:
    """A quantity Observation on a coded rule's code must not trip it."""
    alerts = policy.evaluate(
        {
            "resourceType": "Observation", "id": "obs-x",
            "code": {"coding": [{"code": "foam"}]},
            "valueQuantity": {"value": 1, "code": "mg/L"},
            "subject": {"reference": "Location/x"},
            "effectiveDateTime": "2026-05-04T09:30:00Z",
        }
    )
    assert alerts == []


# -- expert correction ---------------------------------------------------------


def test_a_coded_correction_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="correction_reason"):
        ReviewDecision(reviewer="r@x", coded_value="present")
    with pytest.raises(ValueError, match="not both"):
        ReviewDecision(
            reviewer="r@x", coded_value="present", normalized_value=1.0,
            normalized_unit="mg/L", correction_reason="both",
        )


def test_a_coded_correction_must_still_be_in_the_value_set(service) -> None:
    proposal = service.propose(coded("foam", "kinda foamy"))
    with pytest.raises(ApprovalValidationError, match="not in the reviewed value set"):
        service.approve(
            proposal.id,
            ReviewDecision(reviewer="r@x", coded_value="lots", correction_reason="photo shows foam"),  # noqa: E501
        )
    result = service.approve(
        proposal.id,
        ReviewDecision(reviewer="r@x", coded_value="present", correction_reason="photo shows foam"),
    )
    assert result.observation["valueCodeableConcept"]["coding"][0]["code"] == "present"
    entry = next(
        e for e in service.repository.list_provenance(50) if e.event_type == "mapping-approved"
    )
    assert entry.payload["expert_correction"] is True
    assert entry.payload["published_value_coding"]["code"] == "present"
    assert entry.payload["published_value"] is None


def test_a_quantity_correction_is_refused_for_a_coded_reading(service) -> None:
    proposal = service.propose(coded("foam", "kinda foamy"))
    with pytest.raises(ApprovalValidationError, match="coded_value, not a quantity"):
        service.approve(
            proposal.id,
            ReviewDecision(
                reviewer="r@x", normalized_value=1.0, normalized_unit="mg/L",
                correction_reason="no",
            ),
        )


# -- preview ---------------------------------------------------------------------


def test_the_preview_shows_the_concept_a_word_resolves_to(service) -> None:
    proposal = service.propose(coded("macrophytes", "dense"))
    preview = service.normalization_preview(proposal.id, "macrophytes")
    assert preview.status == "ok"
    assert preview.value_kind == "coded"
    assert preview.normalized_coding.code == "extensive"
    assert [item.code for item in preview.accepted_values] == ["absent", "present", "extensive"]
    assert "'dense' → extensive" in preview.formula


# -- the catalog endpoint ----------------------------------------------------------


def test_the_catalog_exposes_value_sets_and_legs() -> None:
    from fastapi.testclient import TestClient

    from aquafhir import main

    with TestClient(main.app) as client:
        body = client.get("/api/v1/coding/catalog").json()
    by_code = {item["code"]: item for item in body["codes"]}
    assert [v["code"] for v in by_code["foam"]["value_set"]] == ["absent", "present", "extensive"]
    assert by_code["foam"]["accepted_units"] == []
    assert by_code["campylobacter"]["leg"] == "human"
    assert by_code["fishes"]["leg"] == "animal"
    assert by_code["ph"]["leg"] == "environmental"
