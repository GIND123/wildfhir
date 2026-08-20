"""Advisory drafting sits downstream of the deterministic alert decision."""

from datetime import UTC, datetime

import pytest

from aquafhir.models import RawReading, ReviewDecision, SourceType
from aquafhir.service import AiUnavailableError

BRIEFING_RESPONSE = {
    "headline": "Conductivity above demonstration threshold at Oder at Kostrzyn",
    "summary": "Conductivity reached 2.35 mS/cm on 27 July 2022 at oder-kostrzyn.",
    "recommended_actions": [
        "Confirm the reading with an independent sample.",
        "Check drinking-water intakes downstream of the site.",
    ],
    "uncertainty": "Single site, single indicator; the policy is a demonstration policy.",
    "escalation_question": "Is any drinking-water intake within 30 km of this site?",
}

SITUATION_RESPONSE = {
    "headline": "One indicator above threshold at one site",
    "situation": "Conductivity at oder-kostrzyn crossed the demonstration threshold.",
    "by_site": [{"site_code": "oder-kostrzyn", "assessment": "One high conductivity reading."}],
    "data_gaps": ["No dissolved oxygen recorded at this site."],
    "next_steps": ["Increase sampling frequency."],
}


def high_conductivity() -> RawReading:
    return RawReading(
        source_id="pl-agency-001",
        source_type=SourceType.AGENCY,
        parameter="electrical conductivity",
        value=2.35,
        unit="mS/cm",
        observed_at=datetime(2022, 7, 27, 8, tzinfo=UTC),
        site_code="oder-kostrzyn",
        site_name="Oder at Kostrzyn",
        latitude=52.5887,
        longitude=14.6495,
    )


def alert_on(service, fake_gemini):
    fake_gemini.responses = [
        {
            "code": "electrical-conductivity",
            "unit_code": "mS/cm",
            "confidence": 0.95,
            "rationale": "Exact match.",
            "evidence": [],
            "needs_expert_review": False,
        }
    ]
    proposal = service.propose(high_conductivity())
    result = service.approve(proposal.id, ReviewDecision(reviewer="reviewer@example.org"))
    return result.alerts[0]


def test_a_draft_is_produced_per_audience_and_stored(ai_service, fake_gemini):
    alert = alert_on(ai_service, fake_gemini)
    fake_gemini.responses = [BRIEFING_RESPONSE]

    briefing = ai_service.draft_briefing(alert.id, "veterinary")

    assert briefing.audience == "veterinary"
    assert briefing.status == "draft"
    assert "review before any use" in briefing.disclaimer
    assert briefing.ai.template_id == "alert-briefing/v1"
    assert ai_service.repository.list_briefings(alert_id=alert.id)[0].id == briefing.id


def test_the_prompt_carries_the_decided_facts_not_a_request_to_decide(ai_service, fake_gemini):
    alert = alert_on(ai_service, fake_gemini)
    fake_gemini.responses = [BRIEFING_RESPONSE]

    ai_service.draft_briefing(alert.id, "water-authority")
    prompt = fake_gemini.last_prompt

    assert "severity assigned by policy: high" in prompt
    assert "oder-replay-demo-v1" in prompt
    assert "demo-not-for-operational-use" in prompt
    assert "2.35 mS/cm" in prompt


def test_an_audience_the_policy_did_not_route_to_is_refused(ai_service, fake_gemini):
    alert = alert_on(ai_service, fake_gemini)
    # Stored alerts are immutable, so route a distinct alert to one audience.
    restricted = alert.model_copy(
        update={"id": "restricted-alert", "audiences": ["water-authority"]}
    )
    ai_service.repository.save_alert(restricted)
    fake_gemini.responses = [BRIEFING_RESPONSE]

    with pytest.raises(ValueError, match="not routed"):
        ai_service.draft_briefing(restricted.id, "veterinary")


def test_an_unknown_audience_is_refused_before_any_model_call(ai_service, fake_gemini):
    alert = alert_on(ai_service, fake_gemini)

    with pytest.raises(ValueError, match="Unknown audience"):
        ai_service.draft_briefing(alert.id, "press-office")
    assert fake_gemini.responses == []


def test_drafting_is_hash_chained(ai_service, fake_gemini):
    alert = alert_on(ai_service, fake_gemini)
    fake_gemini.responses = [BRIEFING_RESPONSE]

    ai_service.draft_briefing(alert.id, "public-health")
    events = [item.event_type for item in ai_service.repository.list_provenance()]

    assert "briefing-drafted" in events
    assert ai_service.repository.verify_chain().valid is True


def test_the_situation_report_only_sees_stored_records(ai_service, fake_gemini):
    alert_on(ai_service, fake_gemini)
    fake_gemini.responses = [SITUATION_RESPONSE]

    report = ai_service.situation_report()

    assert report.observations_considered == 1
    assert report.alerts_considered == 1
    assert report.pending_reviews == 0
    assert report.by_site[0].site_code == "oder-kostrzyn"
    assert "no prediction" in report.disclaimer
    assert "oder-kostrzyn" in fake_gemini.last_prompt


def test_advisories_need_a_key(service):
    with pytest.raises(AiUnavailableError):
        service.situation_report()
