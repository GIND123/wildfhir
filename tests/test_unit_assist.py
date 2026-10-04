"""Unit review: source preservation, AI attribution, and explicit approval."""

import pytest
from fastapi.testclient import TestClient

from aquafhir import main
from aquafhir.coding_llm import GeminiCodingAgent
from aquafhir.config import AssistMode
from aquafhir.gemini import GeminiError
from aquafhir.models import ReviewDecision, UnitSuggestionResult
from aquafhir.service import ApprovalValidationError, InvalidReviewStateError
from tests.fakes import FakeGemini
from tests.test_coding_llm import gemini_says
from tests.test_review_gate import CONDUCTIVITY, reading


@pytest.mark.parametrize(("code", "source", "value", "expected", "unit"), [
    (CONDUCTIVITY, "\u00b5S/cm", 2444, 2.444, "mS/cm"),
    (CONDUCTIVITY, "\u03bcS / cm", 2444, 2.444, "mS/cm"),
    (CONDUCTIVITY, "us/cm", 2444, 2.444, "mS/cm"),
    ("waterTemperature", "\u00b0C", 20, 20, "Cel"),
    ("nitrate", "\u00b5g / L", 1200, 1.2, "mg/L"),
    ("ph", "pH", 7.2, 7.2, "[pH]"),
    ("coliforms", "CFU / 100 mL", 980, 980, "{cfu}/dL"),
])
def test_alias_preview_matches_publication_and_preserves_source(
    service, code, source, value, expected, unit,
):
    proposal = service.propose(reading(value, source, code))
    preview = service.normalization_preview(proposal.id, code)
    assert preview.status == "ok"
    assert preview.conversion_origin == "reviewed-alias"
    assert preview.normalized_value == pytest.approx(expected)
    result = service.approve(proposal.id, ReviewDecision(reviewer="expert"))
    assert result.observation["valueQuantity"]["value"] == pytest.approx(expected)
    assert result.observation["valueQuantity"]["code"] == unit
    assert result.proposal.reading.unit == source


@pytest.mark.parametrize("unit", ["MS/cm", "ms/cm", "S/cm", "ppm", "C"])
def test_ambiguous_units_are_not_silently_aliased(service, unit):
    assert service.catalog.canonical_unit(unit, service.catalog.rule_for_code(CONDUCTIVITY)) == unit
    assert service.catalog.normalize_unit(
        2, unit, service.catalog.rule_for_code(CONDUCTIVITY)
    )[1] is None


def answer(**changes):
    return {
        "status": "suggested", "interpreted_unit": "[degF]", "target_unit": "Cel",
        "factor": 5 / 9, "offset": -32 * 5 / 9,
        "rationale": "Fahrenheit interpreted as an absolute temperature.", **changes,
    }


def prepare(service, payload=None, *, source="degF", value=68, code="waterTemperature"):
    proposal = service.propose(reading(value, source, code))
    service.gemini = FakeGemini([payload if payload is not None else answer()])
    return proposal


def test_ai_offset_suggestion_is_cached_pending_and_explicitly_accepted(service):
    proposal = prepare(service)
    suggestion = service.suggest_unit_conversion(proposal.id, "waterTemperature").suggestion
    assert suggestion.normalized_value == pytest.approx(20)
    assert suggestion.evidence_status == "uncited"
    assert suggestion.origin == "ai-conversion"
    assert service.suggest_unit_conversion(proposal.id, "waterTemperature").suggestion == suggestion
    assert len(service.gemini.calls) == 1
    preview = service.normalization_preview(proposal.id, "waterTemperature")
    assert preview.status == "unit-unresolved"
    assert preview.normalized_value is None
    assert preview.ai_result.suggestion == suggestion
    with pytest.raises(ApprovalValidationError, match="expert correction"):
        service.approve(proposal.id, ReviewDecision(reviewer="expert"))
    assert service.repository.get_observation_for_proposal(proposal.id) is None
    assert service.repository.list_alerts(50) == []
    result = service.approve(proposal.id, ReviewDecision(
        reviewer="expert", normalized_value=21, normalized_unit="Cel",
        correction_reason="Reviewed and corrected against the field record",
        unit_suggestion_id=suggestion.id,
    ))
    assert result.observation["valueQuantity"]["value"] == 21
    event = next(e for e in service.repository.list_provenance(50)
                 if e.event_type == "mapping-approved")
    assert event.payload["unit_suggestion"]["suggestion"]["normalized_value"] == pytest.approx(20)
    assert event.payload["published_value"] == 21
    assert event.payload["ai_accepted"]
    assert event.payload["unit_suggestion_id"] == suggestion.id
    assert service.repository.verify_chain().valid


def test_intake_ai_unit_interpretation_is_visible_and_requires_explicit_correction(service):
    service.coding_agent = GeminiCodingAgent(
        service.catalog, FakeGemini([gemini_says()]), assist_mode=AssistMode.ALWAYS
    )
    proposal = service.propose(reading(2444, "microsiemens/cm"))
    assert proposal.normalized_value is None
    preview = service.normalization_preview(proposal.id, CONDUCTIVITY)
    assert preview.ai_result.suggestion.origin == "ai-interpretation"
    assert preview.ai_result.suggestion.normalized_value == pytest.approx(2.444)
    with pytest.raises(ApprovalValidationError, match="expert correction"):
        service.approve(proposal.id, ReviewDecision(reviewer="expert"))


def test_reviewed_alias_cannot_be_reinterpreted_by_gemini(service):
    service.coding_agent = GeminiCodingAgent(
        service.catalog, FakeGemini([gemini_says(unit_code="mS/cm")]),
        assist_mode=AssistMode.ALWAYS,
    )
    proposal = service.propose(reading(2444, "\u00b5S/cm"))
    assert proposal.normalized_value == pytest.approx(2.444)
    assert not proposal.unit_suggestions


def test_ai_string_normalization_uses_reviewed_arithmetic(service):
    proposal = prepare(service, answer(
        interpreted_unit="uS/cm", target_unit="mS/cm", factor=999, offset=1000,
    ), source="microsiemens/cm", value=2444, code=CONDUCTIVITY)
    suggestion = service.suggest_unit_conversion(proposal.id, CONDUCTIVITY).suggestion
    assert suggestion.factor == 0.001
    assert suggestion.offset == 0
    assert suggestion.normalized_value == pytest.approx(2.444)


@pytest.mark.parametrize("payload", [
    answer(factor=float("nan")), answer(factor=0), answer(offset=float("inf")),
    answer(target_unit="made-up"), answer(factor=1e100), answer(status="invented"),
    [], {"status": "suggested"}, answer(rationale=""),
])
def test_invalid_ai_responses_leave_manual_review_available(service, payload):
    proposal = prepare(service, payload)
    result = service.suggest_unit_conversion(proposal.id, "waterTemperature")
    assert result.status == "unavailable"
    assert result.suggestion is None
    assert service.repository.get_proposal(proposal.id).status.value == "pending"
    assert service.repository.get_observation_for_proposal(proposal.id) is None
    assert service.repository.verify_chain().valid


def test_no_match_is_cached_without_manufacturing_a_conversion(service):
    proposal = prepare(service, answer(status="no-match", rationale="Source is ambiguous"))
    result = service.suggest_unit_conversion(proposal.id, "waterTemperature")
    assert result.status == "no-match"
    assert result.suggestion is None
    assert service.suggest_unit_conversion(proposal.id, "waterTemperature") == result
    assert len(service.gemini.calls) == 1


def test_mpn_cannot_be_suggested_as_cfu(service):
    proposal = prepare(service, answer(
        interpreted_unit="MPN/100mL", target_unit="{cfu}/dL", factor=1, offset=0,
    ), code="coliforms", source="MPN/100mL", value=980)
    assert service.suggest_unit_conversion(proposal.id, "coliforms").status == "unavailable"


def test_french_npp_cannot_be_suggested_as_cfu(service):
    proposal = prepare(service, answer(
        interpreted_unit="NPP/100mL", target_unit="{cfu}/dL", factor=1, offset=0,
    ), code="coliforms", source="NPP/100mL", value=980)
    assert service.suggest_unit_conversion(proposal.id, "coliforms").status == "unavailable"


def test_intake_mpn_interpretation_is_refused_without_failing_ingestion(service):
    service.coding_agent = GeminiCodingAgent(service.catalog, FakeGemini([gemini_says(
        code="coliforms", unit_code="CFU/100mL",
    )]), assist_mode=AssistMode.ALWAYS)
    proposal = service.propose(reading(980, "MPN/100mL", "coliforms"))
    assert proposal.normalized_value is None
    assert not proposal.unit_suggestions
    assert "AI assist unavailable" in proposal.rationale


def test_correction_cannot_claim_another_suggestion(service):
    proposal = prepare(service)
    with pytest.raises(ApprovalValidationError, match="does not belong"):
        service.approve(proposal.id, ReviewDecision(
            reviewer="expert", normalized_value=20, normalized_unit="Cel",
            correction_reason="Reviewed", unit_suggestion_id="not-this-proposal",
        ))


def test_outage_can_retry_and_assist_off_does_not_call(service):
    proposal = prepare(service)
    service.coding_agent = GeminiCodingAgent(
        service.catalog, service.gemini, assist_mode=AssistMode.OFF
    )
    assert service.suggest_unit_conversion(proposal.id, "waterTemperature").status == "unavailable"
    assert not service.gemini.calls
    service.coding_agent.assist_mode = AssistMode.AUTO
    service.gemini.responses.insert(0, GeminiError("timeout"))
    assert service.suggest_unit_conversion(proposal.id, "waterTemperature").status == "unavailable"
    assert service.suggest_unit_conversion(proposal.id, "waterTemperature").status == "suggested"


def test_slow_suggestion_cannot_reopen_an_approved_record(service, monkeypatch):
    proposal = prepare(service)
    original = service.gemini.generate_json

    def delayed(**kwargs):
        service.approve(proposal.id, ReviewDecision(
            reviewer="expert", normalized_value=20, normalized_unit="Cel",
            correction_reason="Verified independently",
        ))
        return original(**kwargs)

    monkeypatch.setattr(service.gemini, "generate_json", delayed)
    with pytest.raises(InvalidReviewStateError):
        service.suggest_unit_conversion(proposal.id, "waterTemperature")
    assert service.repository.get_proposal(proposal.id).status.value == "approved"
    assert service.repository.save_unit_suggestion(
        proposal.id, "waterTemperature", UnitSuggestionResult(status="no-match", message="test")
    ) is None


def test_legacy_proposal_values_cannot_bypass_the_preview(service):
    proposal = prepare(service)
    proposal.normalized_value, proposal.normalized_unit = 20, "Cel"
    service.repository.save_proposal(proposal)
    preview = service.normalization_preview(proposal.id, "waterTemperature")
    assert preview.status == "unit-unresolved"
    with pytest.raises(ApprovalValidationError):
        service.approve(proposal.id, ReviewDecision(reviewer="expert"))


def test_unit_suggestion_http_contract(service):
    proposal = prepare(service)
    main.app.dependency_overrides[main.get_service] = lambda: service
    try:
        client = TestClient(main.app)
        path = f"/api/v1/proposals/{proposal.id}/unit-suggestion"
        response = client.post(path, params={"code": "waterTemperature"})
        assert response.status_code == 200
        assert response.json()["suggestion"]["normalized_value"] == pytest.approx(20)
        assert client.post(path, params={"code": "unknown"}).status_code == 422
        assert client.post(
            "/api/v1/proposals/missing/unit-suggestion", params={"code": "waterTemperature"}
        ).status_code == 404
    finally:
        main.app.dependency_overrides.clear()
