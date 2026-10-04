"""Edge cases for reviewed unit handling: spellings that fold, scales that never do.

The rule these tests pin down: a *spelling* of a unit with exactly one
physical meaning resolves deterministically; anything that could change the
scale or the measurement basis is withheld for a reviewer. `mg/l` is a
spelling of `mg/L`; `MG/L` is mega-grams and stays unresolved.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aquafhir.coding import ReviewedCodingAgent, range_violation
from aquafhir.models import RawReading, ReviewDecision, SourceType

RULES = Path(__file__).resolve().parents[1] / "config" / "coding-rules.yaml"


@pytest.fixture(scope="module")
def agent() -> ReviewedCodingAgent:
    return ReviewedCodingAgent(RULES)


def rule(agent: ReviewedCodingAgent, code: str) -> dict:
    found = agent.rule_for_code(code)
    assert found is not None
    return found


def reading(parameter: str, value: float, unit: str) -> RawReading:
    return RawReading(
        source_id="t", source_type=SourceType.AGENCY, parameter=parameter, value=value,
        unit=unit, observed_at=datetime.now(UTC), site_code="s", site_name="s",
        latitude=0, longitude=0,
    )


# -- spellings that fold ---------------------------------------------------

@pytest.mark.parametrize(
    ("code", "value", "unit", "expected_value", "expected_unit"),
    [
        ("dissolved-oxygen", 8.2, "mg/l", 8.2, "mg/L"),
        ("lead-dissolved", 15, "ug/l", 15, "ug/L"),
        ("lead-dissolved", 15, "µg/l", 15, "ug/L"),
        ("lead-dissolved", 15, "ppb", 15, "ug/L"),
        ("coliforms", 200, "cfu/100ml", 200, "{cfu}/dL"),
        ("coliforms", 200, "CFU / 100 mL", 200, "{cfu}/dL"),
        ("coliforms", 200, "UFC/100mL", 200, "{cfu}/dL"),     # French CFU, as Hub'Eau writes it
        ("ndci", 0.43, "index", 0.43, "1"),                   # dimensionless, as a bulletin says it
        ("electrical-conductivity", 2350, "US/CM", 2.35, "mS/cm"),
        ("electrical-conductivity", 2350, " uS / cm ", 2.35, "mS/cm"),
        ("waterTemperature", 21.5, "CELSIUS", 21.5, "Cel"),
        ("waterTemperature", 21.5, "degrees Celsius", 21.5, "Cel"),
        ("waterTemperature", 21.5, "°c", 21.5, "Cel"),
        ("ph", 7.4, "pH units", 7.4, "[pH]"),
        ("ph", 7.4, "unite pH", 7.4, "[pH]"),
        ("campylobacter", 500, "per 100,000", 500, "{cases}/100000"),
        ("campylobacter", 500, "cases/100000", 500, "{cases}/100000"),
    ],
)
def test_spelling_variants_resolve(agent, code, value, unit, expected_value, expected_unit):
    got_value, got_unit, note = agent.normalize_unit(value, unit, rule(agent, code))
    assert (got_value, got_unit) == (pytest.approx(expected_value), expected_unit), note
    assert "reviewed alias" in note


# -- scales and bases that never fold ------------------------------------------

@pytest.mark.parametrize(
    ("code", "value", "unit"),
    [
        ("dissolved-oxygen", 8.2, "MG/L"),       # M is mega in UCUM
        ("electrical-conductivity", 2.35, "MS/cm"),
        ("electrical-conductivity", 2.35, "ms/cm"),
        ("waterTemperature", 70, "°F"),
        ("waterTemperature", 294.65, "K"),
        ("waterTemperature", 21.5, "C"),          # coulomb, not Celsius
        ("dissolved-oxygen", 95, "%"),            # saturation, not concentration
        ("dissolved-oxygen", 8.2, "ppm"),
        ("nitrate", 11.3, "mg(N)/L"),             # different reporting basis
        ("coliforms", 200, "MPN/100mL"),          # different estimator
        ("coliforms", 200, "NPP/100mL"),          # the same estimator, as Hub'Eau spells it
        ("coliforms", 200, "cfu/mL"),             # different scale
        ("lead-dissolved", 15, "ng/L"),
        ("campylobacter", 500, "cases"),          # needs the denominator
        ("fishes", 12, "count"),                  # not the UCUM annotation
        ("tss", 30, "g/m3"),
    ],
)
def test_scale_or_basis_changes_are_withheld(agent, code, value, unit):
    got_value, got_unit, note = agent.normalize_unit(value, unit, rule(agent, code))
    assert (got_value, got_unit) == (None, None)
    assert "reviewer correction" in note


# -- numeric edges --------------------------------------------------------------

def test_signed_zero_is_published_as_plain_zero(agent):
    value, unit, _ = agent.normalize_unit(-0.0, "uS/cm", rule(agent, "electrical-conductivity"))
    assert unit == "mS/cm"
    assert value == 0.0 and str(value) == "0.0"


def test_boundaries_of_plausible_range_are_inclusive(agent):
    ec = rule(agent, "electrical-conductivity")
    assert agent.normalize_unit(200_000, "uS/cm", ec)[0] == pytest.approx(200.0)
    assert agent.normalize_unit(200_000.01, "uS/cm", ec)[0] is None
    temp = rule(agent, "waterTemperature")
    assert agent.normalize_unit(-5.0, "Cel", temp)[0] == -5.0
    assert agent.normalize_unit(-5.01, "Cel", temp)[0] is None


def test_overflow_after_conversion_is_withheld(agent):
    value, unit, note = agent.normalize_unit(1e308, "mg/L", rule(agent, "lead-dissolved"))
    assert (value, unit) == (None, None)
    assert "withheld" in note


def test_non_finite_values_never_pass_range_check(agent):
    lead = rule(agent, "lead-dissolved")
    assert range_violation(float("inf"), "ug/L", lead)
    assert range_violation(float("nan"), "ug/L", lead)


def test_fractional_count_is_withheld(agent):
    fishes = rule(agent, "fishes")
    value, unit, note = agent.normalize_unit(12.5, "{count}", fishes)
    assert (value, unit) == (None, None)
    assert "whole number" in note
    assert agent.normalize_unit(12.0, "{count}", fishes)[0] == 12.0


def test_fractional_count_cannot_be_forced_by_expert_correction(service):
    proposal = service.propose(reading("dead fish", 12.5, "{count}"))
    assert proposal.normalized_value is None
    from aquafhir.service import ApprovalValidationError

    with pytest.raises(ApprovalValidationError, match="whole number"):
        service.approve(
            proposal.id,
            ReviewDecision(
                reviewer="r", normalized_value=12.5, normalized_unit="{count}",
                correction_reason="counted half a fish",
            ),
        )
    result = service.approve(
        proposal.id,
        ReviewDecision(
            reviewer="r", normalized_value=12, normalized_unit="{count}",
            correction_reason="two observers, twelve carcasses confirmed",
        ),
    )
    assert result.observation["valueQuantity"]["value"] == 12


# -- expert corrections: spelling folds, scale does not ---------------------------

def test_expert_correction_unit_spelling_is_canonicalised(service):
    proposal = service.propose(reading("dissolved oxygen", -5.0, "mg/L"))
    assert proposal.normalized_value is None, "failed sensor must be withheld"
    result = service.approve(
        proposal.id,
        ReviewDecision(
            reviewer="r", normalized_value=5.1, normalized_unit="mg/l",
            correction_reason="probe re-read on site",
        ),
    )
    quantity = result.observation["valueQuantity"]
    assert (quantity["value"], quantity["code"]) == (5.1, "mg/L")


def test_expert_correction_in_a_source_unit_is_still_refused(service):
    from aquafhir.service import ApprovalValidationError

    proposal = service.propose(reading("conductivity", 2350, "uS/cm"))
    with pytest.raises(ApprovalValidationError, match="not an accepted unit"):
        service.approve(
            proposal.id,
            ReviewDecision(
                reviewer="r", normalized_value=2350, normalized_unit="uS/cm",
                correction_reason="typed the source unit back",
            ),
        )
