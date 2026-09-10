"""A pinned model a key cannot use must not look like a working AI layer.

A judge with a fresh free-tier key gets HTTP 429 for the preview model and
404 for a retired one. Before the fallback, both looked like "AI configured"
in the header and failed silently on every call.
"""

import json
from typing import Any

import pytest

from aquafhir.coding import ReviewedCodingAgent
from aquafhir.coding_llm import GeminiCodingAgent
from aquafhir.config import AssistMode
from aquafhir.gemini import GeminiClient, GeminiError
from tests.test_coding_llm import gemini_says, reading


class PinnedModelUnusable(GeminiClient):
    """The pinned model answers `status`; the fallback model answers properly."""

    def __init__(self, status: int, fallback: str = "gemini-3.1-flash-lite") -> None:
        super().__init__(
            api_key="k", model="gemini-3.1-pro-preview", max_retries=0, fallback_model=fallback
        )
        self.status = status
        self.models_called: list[str] = []

    def _send(self, body: dict[str, Any], model: str) -> str:
        self.models_called.append(model)
        if model == self.model:
            category = {429: "quota-exceeded", 404: "model-not-found", 500: "upstream-error"}[self.status]  # noqa: E501
            raise GeminiError(f"Gemini request failed {self.status}", category=category, status=self.status)  # noqa: E501
        return json.dumps(gemini_says())


@pytest.mark.parametrize("status", [429, 404])
def test_a_quota_or_retired_model_falls_back_and_attributes_the_real_model(status) -> None:
    gemini = PinnedModelUnusable(status)
    copilot = GeminiCodingAgent(
        ReviewedCodingAgent("config/coding-rules.yaml"), gemini, assist_mode=AssistMode.ALWAYS
    )
    proposal = copilot.propose(reading("Leitfähigkeit"))
    assert gemini.models_called == ["gemini-3.1-pro-preview", "gemini-3.1-flash-lite"]
    assert proposal.coding.code == "electrical-conductivity"
    # The model that answered is what is recorded, never the pinned name.
    assert proposal.ai.model == "gemini-3.1-flash-lite"
    assert proposal.ai_audit["model"] == "gemini-3.1-flash-lite"
    assert proposal.ai_audit["fallback_from"] == "gemini-3.1-pro-preview"
    assert proposal.ai_audit["outcome"] == "ok"
    assert gemini.last_call["fallback_from"] == "gemini-3.1-pro-preview"


def test_a_generic_upstream_error_does_not_trigger_the_fallback() -> None:
    gemini = PinnedModelUnusable(500)
    copilot = GeminiCodingAgent(
        ReviewedCodingAgent("config/coding-rules.yaml"), gemini, assist_mode=AssistMode.ALWAYS
    )
    proposal = copilot.propose(reading("EC"))
    assert gemini.models_called == ["gemini-3.1-pro-preview"]
    assert proposal.ai is None
    assert proposal.ai_audit["category"] == "upstream-error"


def test_no_fallback_configured_means_the_old_behaviour() -> None:
    gemini = PinnedModelUnusable(429, fallback="")
    copilot = GeminiCodingAgent(
        ReviewedCodingAgent("config/coding-rules.yaml"), gemini, assist_mode=AssistMode.ALWAYS
    )
    proposal = copilot.propose(reading("EC"))
    assert gemini.models_called == ["gemini-3.1-pro-preview"]
    assert proposal.ai is None
    assert proposal.ai_audit["category"] == "quota-exceeded"
    assert proposal.ai_audit["fallback_from"] is None


def test_a_fallback_equal_to_the_pinned_model_is_ignored() -> None:
    gemini = GeminiClient(api_key="k", model="x", fallback_model="x")
    assert gemini.fallback_model == ""


def test_status_reports_the_fallback_model() -> None:
    from fastapi.testclient import TestClient

    from aquafhir import main

    with TestClient(main.app) as client:
        status = client.get("/api/v1/ai/status").json()
        assert "fallback_model" in status
        health = client.get("/api/v1/health").json()
        assert "ai_fallback_model" in health
