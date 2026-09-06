"""The review gate, which used to be a suggestion rather than a gate.

A reviewer approved a source reading of 2444 uS/cm as 2319 mS/cm. The override
path assigned whatever the request body contained, so the accepted-unit list
was never consulted, the plausible range was never reapplied, and a false
high-severity incident followed. Every test here pins one edge of that hole.
"""

import pytest

from aquafhir.models import Coding, RawReading, ReviewDecision
from aquafhir.service import ApprovalValidationError, InvalidReviewStateError

CONDUCTIVITY = "electrical-conductivity"


def reading(value: float, unit: str, parameter: str = "EC") -> RawReading:
    return RawReading(
        source_id="pl-agency-001", source_type="agency", parameter=parameter,
        value=value, unit=unit, observed_at="2022-07-27T08:00:00Z",
        site_code="oder-kostrzyn", site_name="Oder at Kostrzyn",
        latitude=52.5887, longitude=14.6495,
    )


# -- the deterministic conversion -------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [(2444, 2.444), (2350, 2.35), (1200, 1.2)],
)
def test_microsiemens_converts_by_the_reviewed_factor(service, source, expected) -> None:
    proposal = service.propose(reading(source, "uS/cm"))
    result = service.approve(proposal.id, ReviewDecision(reviewer="r@x"))
    assert result.observation["valueQuantity"]["value"] == pytest.approx(expected)
    assert result.observation["valueQuantity"]["code"] == "mS/cm"


def test_the_preview_shows_the_formula_the_server_will_use(service) -> None:
    proposal = service.propose(reading(2444, "uS/cm"))
    preview = service.normalization_preview(proposal.id, CONDUCTIVITY)
    assert preview.status == "ok"
    assert preview.normalized_value == pytest.approx(2.444)
    assert preview.normalized_unit == "mS/cm"
    assert preview.factor == pytest.approx(0.001)
    assert preview.formula == "2444 uS/cm × 0.001 = 2.444 mS/cm"


def test_the_preview_reports_a_range_breach_instead_of_a_number(service) -> None:
    proposal = service.propose(reading(999999, "mS/cm"))
    preview = service.normalization_preview(proposal.id, CONDUCTIVITY)
    assert preview.status == "out-of-range"
    assert preview.normalized_value is None


def test_a_preview_for_an_unknown_code_is_refused(service) -> None:
    proposal = service.propose(reading(2444, "uS/cm"))
    with pytest.raises(ApprovalValidationError, match="not a code"):
        service.normalization_preview(proposal.id, "not-a-real-code")


# -- what a reviewer may not do ---------------------------------------------


def test_the_reported_bug_is_refused(service) -> None:
    """2444 uS/cm approved as 2319 mS/cm: above the 200 mS/cm plausible maximum."""
    proposal = service.propose(reading(2444, "uS/cm"))
    with pytest.raises(ApprovalValidationError, match="plausible range"):
        service.approve(
            proposal.id,
            ReviewDecision(
                reviewer="r@x", normalized_value=2319.0, normalized_unit="mS/cm",
                correction_reason="transcription",
            ),
        )
    assert service.repository.get_proposal(proposal.id).status.value == "pending"
    assert service.repository.list_alerts(50) == []


def test_an_invented_primary_code_is_refused(service) -> None:
    proposal = service.propose(reading(2444, "uS/cm"))
    with pytest.raises(ApprovalValidationError, match="not a code in the curated catalog"):
        service.approve(
            proposal.id,
            ReviewDecision(
                reviewer="r@x",
                coding=Coding(system="http://evil.example", code="made-up", display="Fake"),
            ),
        )


def test_a_unit_the_rule_does_not_accept_is_refused(service) -> None:
    """`uS/cm` is a legal *source* unit but never a legal published one."""
    proposal = service.propose(reading(2444, "uS/cm"))
    with pytest.raises(ApprovalValidationError, match="not an accepted unit"):
        service.approve(
            proposal.id,
            ReviewDecision(
                reviewer="r@x", normalized_value=2444.0, normalized_unit="uS/cm",
                correction_reason="keep the source unit",
            ),
        )


def test_the_client_cannot_choose_the_published_system_or_display(service) -> None:
    """Only the code is honoured; the rest comes from the reviewed catalog."""
    proposal = service.propose(reading(2444, "uS/cm"))
    result = service.approve(
        proposal.id,
        ReviewDecision(
            reviewer="r@x",
            coding=Coding(system="http://evil.example", code=CONDUCTIVITY, display="Hacked"),
        ),
    )
    published = result.observation["code"]["coding"][0]
    assert published["system"] == service.catalog.system
    assert published["display"] == "Electrical conductivity"


def test_an_unresolvable_unit_cannot_be_approved_without_a_correction(service) -> None:
    proposal = service.propose(reading(6.2, "quarts per fortnight", parameter="dissolved oxygen"))
    with pytest.raises(ApprovalValidationError, match="expert correction"):
        service.approve(proposal.id, ReviewDecision(reviewer="r@x"))


def test_a_proposal_with_no_code_cannot_be_approved_without_choosing_one(service) -> None:
    proposal = service.propose(reading(42.0, "Bq/L", parameter="radon activity concentration"))
    assert proposal.coding is None
    with pytest.raises(InvalidReviewStateError, match="Select a code"):
        service.approve(proposal.id, ReviewDecision(reviewer="r@x"))


# -- expert correction ------------------------------------------------------


def test_an_expert_correction_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="correction_reason"):
        ReviewDecision(reviewer="r@x", normalized_value=3.1, normalized_unit="mS/cm")


def test_a_reason_without_a_quantity_is_refused() -> None:
    with pytest.raises(ValueError, match="normalized_value"):
        ReviewDecision(reviewer="r@x", correction_reason="probe drift")


def test_a_valid_expert_correction_publishes_and_is_recorded(service) -> None:
    proposal = service.propose(reading(2444, "uS/cm"))
    result = service.approve(
        proposal.id,
        ReviewDecision(
            reviewer="r@x", normalized_value=3.1, normalized_unit="mS/cm",
            correction_reason="probe recalibrated after the fact",
        ),
    )
    assert result.observation["valueQuantity"]["value"] == pytest.approx(3.1)
    entry = next(
        e for e in service.repository.list_provenance(50)
        if e.event_type == "mapping-approved"
    )
    assert entry.payload["expert_correction"] is True
    assert entry.payload["correction_reason"] == "probe recalibrated after the fact"
    assert entry.payload["published_value"] == pytest.approx(3.1)
    assert entry.payload["published_unit"] == "mS/cm"
    assert entry.payload["published_coding"]["code"] == CONDUCTIVITY
    assert entry.payload["observation_hash"]


def test_an_expert_correction_still_obeys_the_plausible_range(service) -> None:
    proposal = service.propose(reading(3.6, "mg/L", parameter="dissolved oxygen"))
    with pytest.raises(ApprovalValidationError, match="plausible range"):
        service.approve(
            proposal.id,
            ReviewDecision(
                reviewer="r@x", normalized_value=-5.0, normalized_unit="mg/L",
                correction_reason="sensor read negative",
            ),
        )


def test_a_non_finite_correction_is_refused_at_the_model_boundary() -> None:
    with pytest.raises(ValueError):
        ReviewDecision(
            reviewer="r@x", normalized_value=float("inf"),
            normalized_unit="mS/cm", correction_reason="overflow",
        )


# -- nothing published on refusal -------------------------------------------


def test_a_refused_decision_publishes_nothing_and_raises_no_incident(service) -> None:
    proposal = service.propose(reading(2444, "uS/cm"))
    with pytest.raises(ApprovalValidationError):
        service.approve(
            proposal.id,
            ReviewDecision(
                reviewer="r@x", normalized_value=2319.0, normalized_unit="mS/cm",
                correction_reason="typo",
            ),
        )
    assert service.repository.get_observation_for_proposal(proposal.id) is None
    assert service.repository.list_alerts(50) == []
    assert service.repository.verify_chain().valid


def test_ordinary_approvals_and_immutability_still_work(service) -> None:
    proposal = service.propose(reading(2350, "uS/cm"))
    service.approve(proposal.id, ReviewDecision(reviewer="r@x"))
    with pytest.raises(InvalidReviewStateError, match="immutable"):
        service.approve(proposal.id, ReviewDecision(reviewer="r@x"))


# -- duplicate awareness ----------------------------------------------------


def test_an_identical_reading_is_flagged_but_not_merged(service) -> None:
    first = service.propose(reading(2350, "uS/cm"))
    second = service.propose(reading(2350, "uS/cm"))
    assert first.duplicate_of is None
    assert second.duplicate_of == first.id
    assert "already ingested" in second.rationale


def test_a_different_value_at_the_same_instant_is_not_a_duplicate(service) -> None:
    """A conflict is for a reviewer to see, not something to merge away."""
    service.propose(reading(2350, "uS/cm"))
    other = service.propose(reading(2444, "uS/cm"))
    assert other.duplicate_of is None
