"""AI status must describe what happened, not what was configured.

A present key says nothing about quota, credentials or reachability. Labelling
Gemini "Live" on key presence alone made a quota-exhausted bridge look healthy
while every proposal was quietly falling back to the rules.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from aquafhir import main
from aquafhir.coding import ReviewedCodingAgent
from aquafhir.coding_llm import GeminiCodingAgent
from aquafhir.config import AssistMode, Settings
from aquafhir.gemini import GeminiClient, GeminiError, error_category
from aquafhir.models import RawReading

READING = RawReading(
    source_id="pl-agency-001", source_type="agency", parameter="Leitfähigkeit",
    value=2350, unit="uS/cm", observed_at="2022-07-27T08:00:00Z",
    site_code="oder-kostrzyn", site_name="Oder at Kostrzyn",
    latitude=52.5887, longitude=14.6495,
)


class QuotaExhausted(GeminiClient):
    """Enabled and configured, but every call returns 429."""

    def __init__(self) -> None:
        super().__init__(api_key="test-key", model="gemini-test", max_retries=0)

    def _post_with_retries(self, body):  # noqa: ANN001
        raise GeminiError(
            'Gemini transient error 429: {"error":{"message":"quota","status":'
            '"RESOURCE_EXHAUSTED"}}',
            category="quota-exceeded", status=429,
        )


@pytest.mark.parametrize(
    ("status", "category"),
    [(429, "quota-exceeded"), (401, "auth-failed"), (403, "auth-failed"),
     (408, "timeout"), (500, "upstream-error"), (503, "upstream-error")],
)
def test_upstream_statuses_map_to_actionable_categories(status, category) -> None:
    assert error_category(status) == category


def test_a_quota_failure_falls_back_to_the_rules_and_is_recorded(curated_agent) -> None:
    client = QuotaExhausted()
    agent = GeminiCodingAgent(curated_agent, client, assist_mode=AssistMode.ALWAYS)

    proposal = agent.propose(READING)

    # The deterministic pipeline still produced a usable proposal.
    assert proposal.ai is None
    assert "AI assist unavailable" in proposal.rationale
    # And the failure itself is remembered, with no raw provider body.
    assert client.last_call["outcome"] == "error"
    assert client.last_call["category"] == "quota-exceeded"
    assert client.last_call["http_status"] == 429
    assert client.last_call["model"] == "gemini-test"
    assert "latency_ms" in client.last_call and "at" in client.last_call
    assert "RESOURCE_EXHAUSTED" not in str(client.last_call)


def test_a_successful_call_is_recorded_as_ok(fake_gemini) -> None:
    fake_gemini.responses.append({"ok": True})
    fake_gemini.generate_json(
        template_id="t/v1", system="s", prompt="p", schema={"type": "object"}
    )
    assert fake_gemini.last_call["outcome"] == "ok"
    assert fake_gemini.last_call["category"] is None
    assert fake_gemini.last_call["template_id"] == "t/v1"


def test_status_reports_degraded_after_a_quota_failure(tmp_path, curated_agent, monkeypatch):
    """The pill and the Integrations card both read this."""
    from aquafhir.fhir import FhirClient
    from aquafhir.repository import Repository
    from aquafhir.service import BridgeService
    from aquafhir.thresholds import ThresholdPolicy

    client = QuotaExhausted()
    service = BridgeService(
        repository=Repository(tmp_path / "t.db"),
        coding_agent=GeminiCodingAgent(curated_agent, client, assist_mode=AssistMode.ALWAYS),
        thresholds=ThresholdPolicy("config/thresholds.yaml"),
        fhir_client=FhirClient("http://unused/fhir", False, 1),
        gemini=client,
    )
    service.propose(READING)

    settings = Settings(_env_file=None, gemini_api_key="test-key", gemini_model="gemini-test")
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main.app.dependency_overrides[main.get_service] = lambda: service
    try:
        body = TestClient(main.app).get("/api/v1/ai/status").json()
    finally:
        main.app.dependency_overrides.clear()

    assert body["configured"] is True
    assert body["health"] == "quota-exceeded"
    assert body["last_call"]["http_status"] == 429
    assert "quota exceeded" in body["detail"].lower()
    # The reviewer is told the pipeline still worked.
    assert "rules fallback" in body["detail"]


def test_status_says_unknown_before_any_call(tmp_path, curated_agent, monkeypatch):
    """A configured key alone is never evidence that calls succeed."""
    from aquafhir.fhir import FhirClient
    from aquafhir.repository import Repository
    from aquafhir.service import BridgeService
    from aquafhir.thresholds import ThresholdPolicy

    client = GeminiClient(api_key="test-key", model="gemini-test")
    service = BridgeService(
        repository=Repository(tmp_path / "t.db"),
        coding_agent=ReviewedCodingAgent("config/coding-rules.yaml"),
        thresholds=ThresholdPolicy("config/thresholds.yaml"),
        fhir_client=FhirClient("http://unused/fhir", False, 1),
        gemini=client,
    )
    settings = Settings(_env_file=None, gemini_api_key="test-key", gemini_model="gemini-test")
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main.app.dependency_overrides[main.get_service] = lambda: service
    try:
        body = TestClient(main.app).get("/api/v1/ai/status").json()
    finally:
        main.app.dependency_overrides.clear()

    assert body["configured"] is True
    assert body["health"] == "unknown"
    assert "no call has been made" in body["detail"].lower()


def test_a_transport_429_is_categorised_before_it_reaches_the_service(monkeypatch) -> None:
    client = GeminiClient(api_key="k", model="m", max_retries=0)
    monkeypatch.setattr(
        httpx.Client, "get", lambda *a, **k: None, raising=False
    )
    monkeypatch.setattr(
        httpx.Client, "post",
        lambda self, url, **kw: httpx.Response(429, json={"error": "quota"}),
    )
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(GeminiError) as caught:
        client.generate_json(
            template_id="t/v1", system="s", prompt="p", schema={"type": "object"}
        )
    assert caught.value.category == "quota-exceeded"
    assert caught.value.status == 429
    assert client.last_call["category"] == "quota-exceeded"


# -- nothing from the provider crosses the API boundary ---------------------


class Quota429(GeminiClient):
    """Every call fails with a 429 whose body carries provider detail."""

    BODY = (
        '{"error":{"code":429,"message":"Quota exceeded for quota metric '
        'Generate requests","status":"RESOURCE_EXHAUSTED"}}'
    )

    def __init__(self) -> None:
        super().__init__(api_key="test-key", model="gemini-test", max_retries=0)

    def _post_with_retries(self, body):  # noqa: ANN001
        raise GeminiError(
            f"Gemini transient error 429: {self.BODY}",
            category="quota-exceeded", status=429,
        )


# A reading the curated rules *can* code, so approving it raises an incident
# for the advisory drafter to fail on.
ALERTING = RawReading(
    source_id="pl-agency-001", source_type="agency", parameter="EC",
    value=2350, unit="uS/cm", observed_at="2022-07-27T08:00:00Z",
    site_code="oder-kostrzyn", site_name="Oder at Kostrzyn",
    latitude=52.5887, longitude=14.6495,
)


def _alert_service(tmp_path, curated_agent, client):
    from aquafhir.briefing import BriefingWriter
    from aquafhir.fhir import FhirClient
    from aquafhir.models import ReviewDecision
    from aquafhir.repository import Repository
    from aquafhir.service import BridgeService
    from aquafhir.thresholds import ThresholdPolicy

    service = BridgeService(
        repository=Repository(tmp_path / "t.db"), coding_agent=curated_agent,
        thresholds=ThresholdPolicy("config/thresholds.yaml"),
        fhir_client=FhirClient("http://unused/fhir", False, 1),
        briefing_writer=BriefingWriter(client), gemini=client,
    )
    proposal = service.propose(ALERTING)
    service.approve(proposal.id, ReviewDecision(reviewer="r@x"))
    alerts = service.repository.list_alerts(10)
    assert alerts, "the fixture must raise an incident to draft an advisory for"
    return service, alerts[0]


def test_a_429_advisory_failure_returns_a_safe_502(tmp_path, curated_agent, monkeypatch):
    """The reviewer learns the cause. The provider's body stays in the log."""
    client = Quota429()
    service, alert = _alert_service(tmp_path, curated_agent, client)

    settings = Settings(_env_file=None, gemini_api_key="test-key", gemini_model="gemini-test")
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main.app.dependency_overrides[main.get_service] = lambda: service
    try:
        response = TestClient(main.app).post(
            f"/api/v1/alerts/{alert.id}/briefings", params={"audience": "veterinary"}
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "quota-exceeded"
    assert "quota exceeded" in body["detail"].lower()
    # None of the provider's payload may appear in the response.
    for leak in ("RESOURCE_EXHAUSTED", "quota metric", "Generate requests", "{"):
        assert leak not in body["detail"]


def test_a_failed_advisory_call_is_hash_chained(tmp_path, curated_agent):
    """A failure that produced nothing must still leave a trace."""
    client = Quota429()
    service, alert = _alert_service(tmp_path, curated_agent, client)
    with pytest.raises(GeminiError):
        service.draft_briefing(alert.id, "veterinary")

    calls = [e for e in service.repository.list_provenance(50) if e.event_type == "ai-call"]
    assert calls, "the failed call is missing from the chain"
    payload = calls[0].payload
    assert payload["outcome"] == "error"
    assert payload["category"] == "quota-exceeded"
    assert payload["http_status"] == 429
    assert payload["operation"] == "alert-briefing"
    assert payload["model"] == "gemini-test"
    assert payload["prompt_hash"] and payload["latency_ms"] >= 0 and payload["at"]
    # No prompt text and no provider body may be stored.
    blob = str(payload)
    assert "RESOURCE_EXHAUSTED" not in blob and "quota metric" not in blob
    assert service.repository.verify_chain().valid


def test_a_successful_call_is_chained_with_its_prompt_hash(ai_service, fake_gemini):
    fake_gemini.responses.append(
        {"code": "electrical-conductivity", "unit": "uS/cm", "confidence": 0.9,
         "evidence": ["EC"], "rationale": "ok", "needs_expert_review": False}
    )
    proposal = ai_service.propose(READING)
    calls = [e for e in ai_service.repository.list_provenance(50) if e.event_type == "ai-call"]
    assert len(calls) == 1
    assert calls[0].payload["outcome"] == "ok"
    assert calls[0].payload["operation"] == "coding-proposer"
    assert calls[0].payload["prompt_hash"] == proposal.ai.prompt_hash


# -- success means a usable answer, not merely bytes ------------------------


def test_unparseable_output_is_not_recorded_as_success(fake_gemini) -> None:
    fake_gemini.responses.append("this is not JSON at all")
    with pytest.raises(GeminiError) as caught:
        fake_gemini.generate_json(
            template_id="coding-proposer/v1", system="s", prompt="p",
            schema={"type": "object"},
        )
    assert caught.value.category == "invalid-json"
    assert fake_gemini.last_call["outcome"] == "error"
    assert fake_gemini.last_call["category"] == "invalid-json"


def test_an_out_of_catalog_code_marks_the_call_rejected(curated_agent, fake_gemini) -> None:
    """The transport succeeded and the JSON parsed, but the answer was unusable."""
    fake_gemini.responses.append(
        {"code": "not-a-real-code", "unit": "uS/cm", "confidence": 0.99,
         "evidence": ["EC"], "rationale": "guess", "needs_expert_review": False}
    )
    agent = GeminiCodingAgent(curated_agent, fake_gemini, assist_mode=AssistMode.ALWAYS)
    proposal = agent.propose(READING)

    assert proposal.ai is None, "the out-of-catalog answer was discarded"
    assert fake_gemini.last_call["outcome"] == "rejected"
    assert fake_gemini.last_call["category"] == "out-of-catalog"


def test_a_blocked_prompt_is_categorised(fake_gemini) -> None:
    fake_gemini.responses.append(GeminiError("blocked", category="blocked"))
    with pytest.raises(GeminiError):
        fake_gemini.generate_json(
            template_id="t/v1", system="s", prompt="p", schema={"type": "object"}
        )
    assert fake_gemini.last_call["category"] == "blocked"


# -- audit records are call-scoped, not shared client state -----------------


def test_the_record_travels_with_the_result(fake_gemini) -> None:
    fake_gemini.responses.append({"ok": True})
    result = fake_gemini.generate_json(
        template_id="coding-proposer/v1", system="s", prompt="p", schema={"type": "object"}
    )
    assert result.audit["outcome"] == "ok"
    assert result.audit["prompt_hash"] == result.prompt_hash
    assert result.audit["operation"] == "coding-proposer"


def test_the_record_travels_with_the_error(fake_gemini) -> None:
    fake_gemini.responses.append(
        GeminiError("boom", category="quota-exceeded", status=429)
    )
    with pytest.raises(GeminiError) as caught:
        fake_gemini.generate_json(
            template_id="alert-briefing/v1", system="s", prompt="p", schema={"type": "object"}
        )
    assert caught.value.audit["outcome"] == "error"
    assert caught.value.audit["category"] == "quota-exceeded"
    assert caught.value.audit["operation"] == "alert-briefing"


def test_degrading_one_record_leaves_another_alone() -> None:
    """The bug this replaced: downgrading "the last call" hit whatever ran last."""
    from aquafhir.gemini import mark_degraded

    mine = {"outcome": "ok", "category": None, "operation": "coding-proposer"}
    theirs = {"outcome": "ok", "category": None, "operation": "intake"}
    mark_degraded(mine, "out-of-catalog")
    assert mine["outcome"] == "rejected"
    assert theirs["outcome"] == "ok", "a concurrent request's record was corrupted"


def test_concurrent_proposals_each_chain_their_own_call(tmp_path, curated_agent) -> None:
    """Two requests in flight must not claim each other's audit records."""
    import threading

    from aquafhir.fhir import FhirClient
    from aquafhir.repository import Repository
    from aquafhir.service import BridgeService
    from aquafhir.thresholds import ThresholdPolicy
    from tests.fakes import FakeGemini

    class SlowGemini(FakeGemini):
        """Overlaps two calls so a shared queue would visibly interleave."""

        def _post_with_retries(self, body):  # noqa: ANN001
            import json as _json
            import time as _time

            _time.sleep(0.05)
            return _json.dumps(
                {"code": "electrical-conductivity", "unit": "uS/cm", "confidence": 0.9,
                 "evidence": ["EC"], "rationale": "ok", "needs_expert_review": False}
            )

    client = SlowGemini()
    service = BridgeService(
        repository=Repository(tmp_path / "t.db"),
        coding_agent=GeminiCodingAgent(curated_agent, client, assist_mode=AssistMode.ALWAYS),
        thresholds=ThresholdPolicy("config/thresholds.yaml"),
        fhir_client=FhirClient("http://unused/fhir", False, 1),
        gemini=client,
    )
    made: list = []
    threads = [
        threading.Thread(target=lambda: made.append(service.propose(ALERTING)))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    calls = [e for e in service.repository.list_provenance(50) if e.event_type == "ai-call"]
    assert len(calls) == 4, "every concurrent call must be chained exactly once"
    # Each record is chained against the proposal that actually made it.
    by_entity = {e.entity_id: e.payload["prompt_hash"] for e in calls}
    for proposal in made:
        assert by_entity[proposal.id] == proposal.ai_audit["prompt_hash"]
    assert service.repository.verify_chain().valid


def test_an_intake_call_is_attributed_to_the_intake_not_its_first_reading(
    ai_service, fake_gemini
) -> None:
    """The misattribution this replaced.

    `ingest_unstructured` calls `propose()` per extracted reading, and each
    `propose()` used to drain the shared queue. The intake's own call was
    therefore chained against the first proposal instead of the intake.
    """
    from aquafhir.models import IntakeRequest

    fake_gemini.responses.append({
        "readings": [
            {"parameter": "EC", "value": 2350, "unit": "uS/cm",
             "observed_at": "2022-07-27T08:00:00Z", "quoted_span": "EC 2350"},
            {"parameter": "dissolved oxygen", "value": 3.6, "unit": "mg/L",
             "observed_at": "2022-07-27T08:00:00Z", "quoted_span": "O2 3.6"},
        ],
        "warnings": [],
    })
    result = ai_service.ingest_unstructured(
        IntakeRequest(text="EC 2350 uS/cm. Dissolved oxygen 3.6 mg/L.")
    )
    assert len(result.proposals) == 2

    calls = [e for e in ai_service.repository.list_provenance(50) if e.event_type == "ai-call"]
    by_op = {}
    for entry in calls:
        by_op.setdefault(entry.payload["operation"], []).append(entry)

    # Exactly one intake call, chained against the intake and not against a
    # proposal it produced.
    assert len(by_op["intake-extractor"]) == 1
    intake_call = by_op["intake-extractor"][0]
    assert intake_call.entity_id == result.ai.prompt_hash
    assert intake_call.entity_id not in {p.id for p in result.proposals}

    # The per-reading coding calls belong to their own proposals.
    coding_entities = {e.entity_id for e in by_op["coding-proposer"]}
    assert coding_entities == {p.id for p in result.proposals}
    assert ai_service.repository.verify_chain().valid
