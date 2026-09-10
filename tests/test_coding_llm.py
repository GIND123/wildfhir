"""The guardrails around the Gemini coding co-pilot.

Each test states the failure it prevents, because these are the checks that let
the project claim an AI is in the loop without an AI being able to publish.
"""

from datetime import UTC, datetime

import pytest

from aquafhir.coding import ReviewedCodingAgent
from aquafhir.coding_llm import GeminiCodingAgent
from aquafhir.config import AssistMode
from aquafhir.models import ProposerKind, RawReading, ReviewStatus, SourceType
from tests.fakes import BrokenGemini, FakeGemini


def reading(parameter: str, unit: str = "uS/cm", value: float = 2350.0) -> RawReading:
    return RawReading(
        source_id="pl-agency-001",
        source_type=SourceType.AGENCY,
        parameter=parameter,
        value=value,
        unit=unit,
        observed_at=datetime(2022, 7, 27, 8, tzinfo=UTC),
        site_code="oder-kostrzyn",
        site_name="Oder at Kostrzyn",
        latitude=52.5887,
        longitude=14.6495,
    )


def gemini_says(**overrides):
    payload = {
        "code": "electrical-conductivity",
        "unit_code": "uS/cm",
        "confidence": 0.93,
        "rationale": "German 'Leitfähigkeit' is electrical conductivity.",
        "evidence": ["Leitfähigkeit"],
        "needs_expert_review": False,
    }
    payload.update(overrides)
    return payload


def agent(responses, **kwargs) -> tuple[GeminiCodingAgent, FakeGemini]:
    fake = FakeGemini(responses)
    curated = ReviewedCodingAgent("config/coding-rules.yaml")
    kwargs.setdefault("assist_mode", AssistMode.ALWAYS)
    return GeminiCodingAgent(curated, fake, **kwargs), fake


def test_it_maps_a_label_string_similarity_cannot_reach():
    """`Leitfähigkeit` scores far below the alias floor; the curated agent gives up."""
    curated = ReviewedCodingAgent("config/coding-rules.yaml").propose(reading("Leitfähigkeit"))
    assert curated.coding is None

    copilot, _ = agent([gemini_says()])
    proposal = copilot.propose(reading("Leitfähigkeit"))

    assert proposal.coding is not None
    assert proposal.coding.code == "electrical-conductivity"
    assert proposal.proposer is ProposerKind.GEMINI_ASSISTED
    assert proposal.status is ReviewStatus.PENDING
    assert proposal.requires_review is True


def test_the_published_number_is_computed_from_reviewed_factors_only():
    """The model names the unit; the YAML factor does the arithmetic."""
    copilot, fake = agent([gemini_says(confidence=0.99)])
    proposal = copilot.propose(reading("Leitfähigkeit", unit="uS/cm", value=2350.0))

    assert proposal.normalized_value == 2.35  # 2350 uS/cm * 0.001 from coding-rules.yaml
    assert proposal.normalized_unit == "mS/cm"
    assert "2.35" not in fake.last_prompt  # the model was never shown the answer


def test_display_text_comes_from_the_catalog_not_the_model():
    copilot, _ = agent([gemini_says()])
    proposal = copilot.propose(reading("Leitfähigkeit"))

    assert proposal.coding.display == "Electrical conductivity"
    assert proposal.coding.system.endswith("temporarySystem-oah-eu")


def test_confidence_is_capped_so_no_proposal_ever_looks_self_approving():
    copilot, _ = agent([gemini_says(confidence=1.0)], confidence_ceiling=0.95)
    proposal = copilot.propose(reading("Leitfähigkeit"))

    assert proposal.confidence <= 0.95
    assert proposal.requires_review is True


def test_an_out_of_catalog_code_is_refused_and_falls_back_to_curated():
    copilot, _ = agent([gemini_says(code="chlorophyll-a-concentration")])
    proposal = copilot.propose(reading("EC"))

    # Fallback keeps the deterministic answer rather than trusting the model.
    assert proposal.proposer is ProposerKind.CURATED
    assert proposal.coding.code == "electrical-conductivity"
    assert "AI assist unavailable" in proposal.rationale


def test_no_match_withholds_a_code_instead_of_guessing():
    copilot, _ = agent(
        [
            gemini_says(
                code="NO_MATCH",
                unit_code="NO_MATCH",
                rationale="Rainbow foam is not an indicator.",
            )
        ]
    )
    proposal = copilot.propose(reading("mystery rainbow foam", unit="1", value=1))

    assert proposal.coding is None
    assert proposal.normalized_value is None
    assert proposal.confidence == 0.0
    assert "reviewer must supply a code or reject" in proposal.rationale


def test_disagreement_with_the_curated_match_is_flagged_and_penalised():
    copilot, _ = agent([gemini_says(code="chloride", unit_code="NO_MATCH", confidence=0.95)])
    proposal = copilot.propose(reading("EC", unit="mg/L", value=120))

    assert proposal.ai.disagreed_with_rules is True
    assert proposal.confidence <= 0.80
    assert "disagrees with the curated alias match" in proposal.rationale


def test_a_unit_the_model_invents_for_this_code_is_ignored():
    copilot, _ = agent([gemini_says(unit_code="mg/L")])
    proposal = copilot.propose(reading("Leitfähigkeit", unit="microsiemens/cm"))

    # mg/L is a known unit globally but not valid for conductivity, and the
    # source string resolves to nothing, so no quantity may be published.
    assert "not valid for electrical-conductivity" in proposal.rationale
    assert proposal.normalized_value is None
    assert proposal.normalized_unit is None


def test_an_unresolvable_unit_blocks_the_quantity_not_the_proposal():
    copilot, _ = agent([gemini_says(unit_code="NO_MATCH")])
    proposal = copilot.propose(reading("Leitfähigkeit", unit="ppm-ish"))

    assert proposal.coding is not None
    assert proposal.normalized_value is None
    assert proposal.confidence <= 0.69


def test_every_call_is_attributable():
    copilot, _ = agent([gemini_says()])
    proposal = copilot.propose(reading("Leitfähigkeit"))

    assert proposal.ai.provider == "google-gemini"
    assert proposal.ai.template_id == "coding-proposer/v2"
    assert len(proposal.ai.prompt_hash) == 64
    assert "electrical-conductivity" in proposal.ai.grounded_codes
    assert proposal.ai.evidence == ["Leitfähigkeit"]


def test_the_schema_enum_closes_the_vocabulary():
    copilot, fake = agent([gemini_says()])
    copilot.propose(reading("Leitfähigkeit"))

    code_enum = fake.last_schema["properties"]["code"]["enum"]
    assert "NO_MATCH" in code_enum
    assert set(code_enum) - {"NO_MATCH"} == set(copilot.base.codes())


def test_an_upstream_outage_degrades_to_the_curated_pipeline():
    curated = ReviewedCodingAgent("config/coding-rules.yaml")
    copilot = GeminiCodingAgent(curated, BrokenGemini(), assist_mode=AssistMode.ALWAYS)

    proposal = copilot.propose(reading("EC"))

    assert proposal.coding.code == "electrical-conductivity"
    assert proposal.normalized_value == 2.35
    assert proposal.ai is None
    assert "AI assist unavailable" in proposal.rationale


@pytest.mark.parametrize(
    ("mode", "parameter", "expected"),
    [
        (AssistMode.OFF, "Leitfähigkeit", False),
        (AssistMode.ALWAYS, "electrical conductivity", True),
        (AssistMode.AUTO, "electrical conductivity", False),  # exact alias, no call needed
        (AssistMode.AUTO, "Leitfähigkeit", True),  # weak match, worth a call
    ],
)
def test_auto_mode_spends_a_call_only_where_rules_are_weak(mode, parameter, expected):
    copilot, _ = agent([gemini_says()], assist_mode=mode)
    baseline = copilot.base.propose(reading(parameter, unit="mS/cm", value=2.35))

    assert copilot.should_consult(baseline) is expected


def test_a_missing_key_means_the_copilot_never_engages():
    curated = ReviewedCodingAgent("config/coding-rules.yaml")
    copilot = GeminiCodingAgent(curated, FakeGemini(api_key=""), assist_mode=AssistMode.ALWAYS)

    proposal = copilot.propose(reading("Leitfähigkeit"))

    assert copilot.available is False
    assert proposal.proposer is ProposerKind.CURATED


def test_a_unit_that_already_resolves_is_never_reinterpreted():
    """A plausible misreading must not silently rescale a published value."""
    copilot, _ = agent([gemini_says(unit_code="uS/cm")])
    proposal = copilot.propose(reading("Leitfähigkeit", unit="mS/cm", value=2.35))

    assert proposal.normalized_value == 2.35  # not 0.00235
    assert proposal.normalized_unit == "mS/cm"
    assert "already resolves" in proposal.rationale


# -- coded values ------------------------------------------------------------


def coded_reading(parameter: str, word: str) -> RawReading:
    return RawReading(
        source_id="oah-app", source_type=SourceType.CITIZEN, parameter=parameter,
        coded_value=word, observed_at=datetime(2026, 5, 4, 9, tzinfo=UTC),
        site_code="coselhas", site_name="Ribeira de Coselhas", latitude=40.219, longitude=-8.423,
    )


def test_the_model_may_name_which_value_set_concept_a_word_means():
    """'a bit of scum' is not in the value set; the model says it means 'present'."""
    copilot, fake = agent([gemini_says(code="foam", unit_code="NO_MATCH", value_code="present")])
    proposal = copilot.propose(coded_reading("scum on the surface", "a bit of scum"))
    assert proposal.coding.code == "foam"
    assert proposal.normalized_coding.code == "present"
    assert "AI read coded value 'a bit of scum' as 'present'" in proposal.rationale
    assert "present" in fake.last_schema["properties"]["value_code"]["enum"]
    assert "a bit of scum" in fake.last_prompt


def test_a_word_that_already_resolves_is_never_reinterpreted():
    copilot, _ = agent([gemini_says(code="foam", unit_code="NO_MATCH", value_code="extensive")])
    proposal = copilot.propose(coded_reading("foam", "present"))
    assert proposal.normalized_coding.code == "present"


def test_a_model_value_outside_the_set_is_ignored():
    copilot, _ = agent([gemini_says(code="foam", unit_code="NO_MATCH", value_code="lots")])
    proposal = copilot.propose(coded_reading("foam", "kinda foamy"))
    assert proposal.normalized_coding is None
    assert proposal.confidence <= 0.69
    assert "not in the value set" in proposal.rationale
