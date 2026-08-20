"""Unstructured intake: extraction is a proposal, never a publication."""

import pytest

from aquafhir.models import IntakeRequest, ReviewStatus
from aquafhir.service import AiUnavailableError

BULLETIN = """
WIOŚ Szczecin, 27.07.2022 08:00 UTC — Oder at Kostrzyn.
Leitfähigkeit 2350 uS/cm gemessen. Sauerstoff 3.6 mg/L.
Anglers report dead fish downstream; no measurement taken.
"""


def extraction(**overrides):
    payload = {
        "readings": [
            {
                "parameter": "Leitfähigkeit",
                "value": 2350,
                "unit": "uS/cm",
                "observed_at": "2022-07-27T08:00:00Z",
                "site_name": "Oder at Kostrzyn",
                "site_code": "oder-kostrzyn",
                "latitude": 52.5887,
                "longitude": 14.6495,
                "source_type": "agency",
                "quoted_span": "Leitfähigkeit 2350 uS/cm",
            },
            {
                "parameter": "Sauerstoff",
                "value": 3.6,
                "unit": "mg/L",
                "observed_at": "2022-07-27T08:00:00Z",
                "site_name": "Oder at Kostrzyn",
                "site_code": "oder-kostrzyn",
                "latitude": 52.5887,
                "longitude": 14.6495,
                "source_type": "agency",
                "quoted_span": "Sauerstoff 3.6 mg/L",
            },
        ],
        "warnings": ["Dead-fish report carries no measurement and was not extracted."],
    }
    payload.update(overrides)
    return payload


def test_a_bulletin_becomes_pending_proposals(ai_service, fake_gemini):
    fake_gemini.responses = [
        extraction(),
        {
            "code": "electrical-conductivity",
            "unit_code": "uS/cm",
            "confidence": 0.92,
            "rationale": "German for conductivity.",
            "evidence": [],
            "needs_expert_review": False,
        },
        {
            "code": "dissolved-oxygen",
            "unit_code": "mg/L",
            "confidence": 0.9,
            "rationale": "German for dissolved oxygen.",
            "evidence": [],
            "needs_expert_review": False,
        },
    ]

    result = ai_service.ingest_unstructured(IntakeRequest(text=BULLETIN))

    assert result.extracted_count == 2
    assert len(result.proposals) == 2
    assert all(item.status is ReviewStatus.PENDING for item in result.proposals)
    assert result.warnings
    assert result.ai.template_id == "intake-extractor/v1"


def test_the_source_label_and_unit_survive_extraction_untouched(ai_service, fake_gemini):
    fake_gemini.responses = [
        extraction(readings=[extraction()["readings"][0]]),
        {
            "code": "electrical-conductivity",
            "unit_code": "uS/cm",
            "confidence": 0.92,
            "rationale": "German for conductivity.",
            "evidence": [],
            "needs_expert_review": False,
        },
    ]

    result = ai_service.ingest_unstructured(IntakeRequest(text=BULLETIN))
    reading = result.proposals[0].reading

    assert reading.parameter == "Leitfähigkeit"
    assert reading.unit == "uS/cm"
    assert reading.raw_payload["quoted_span"] == "Leitfähigkeit 2350 uS/cm"


def test_a_missing_timestamp_is_flagged_never_invented(ai_service, fake_gemini):
    row = extraction()["readings"][0] | {"observed_at": None}
    fake_gemini.responses = [
        extraction(readings=[row], warnings=[]),
        {
            "code": "electrical-conductivity",
            "unit_code": "uS/cm",
            "confidence": 0.92,
            "rationale": "ok",
            "evidence": [],
            "needs_expert_review": False,
        },
    ]

    result = ai_service.ingest_unstructured(IntakeRequest(text=BULLETIN))

    assert any("timestamp" in warning for warning in result.warnings)
    assert result.proposals[0].reading.raw_payload["observed_at_in_source"] is None


def test_an_invalid_extraction_is_discarded_with_a_warning(ai_service, fake_gemini):
    broken = extraction()["readings"][0] | {"latitude": 999.0}
    fake_gemini.responses = [extraction(readings=[broken], warnings=[])]

    result = ai_service.ingest_unstructured(IntakeRequest(text=BULLETIN))

    assert result.proposals == []
    assert any("failed validation" in warning for warning in result.warnings)


def test_extraction_is_recorded_in_the_hash_chain(ai_service, fake_gemini):
    fake_gemini.responses = [extraction(readings=[], warnings=["nothing measurable"])]

    ai_service.ingest_unstructured(IntakeRequest(text=BULLETIN))
    events = [item.event_type for item in ai_service.repository.list_provenance()]

    assert "unstructured-intake" in events
    assert ai_service.repository.verify_chain().valid is True


def test_intake_without_a_key_fails_closed_with_a_useful_message(service):
    with pytest.raises(AiUnavailableError, match="GEMINI_API_KEY"):
        service.ingest_unstructured(IntakeRequest(text=BULLETIN))


def test_an_extraction_missing_a_required_field_is_a_warning_not_a_crash(
    ai_service, fake_gemini
):
    incomplete = {"parameter": "Leitfähigkeit", "unit": "uS/cm", "source_type": "agency"}
    fake_gemini.responses = [extraction(readings=[incomplete], warnings=[])]

    result = ai_service.ingest_unstructured(IntakeRequest(text=BULLETIN))

    assert result.proposals == []
    assert any("failed validation" in warning for warning in result.warnings)
