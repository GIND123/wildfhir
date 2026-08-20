"""Transport behaviour: the failure modes that would otherwise surface mid-demo."""

import json

import httpx
import pytest

from aquafhir import gemini as gemini_module
from aquafhir.coding import ReviewedCodingAgent
from aquafhir.coding_llm import GeminiCodingAgent
from aquafhir.config import AssistMode, Settings
from aquafhir.gemini import GeminiClient, GeminiError
from aquafhir.main import build_coding_agent, build_gemini_client

SCHEMA = {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}, "required": ["ok"]}


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


def ok_payload(text: str = '{"ok": true}') -> FakeResponse:
    body = {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}
        ]
    }
    return FakeResponse(200, json.dumps(body))


@pytest.fixture
def transport(monkeypatch):
    """Replace httpx.Client inside the gemini module with a recording double."""
    state = {"queue": [], "requests": []}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, json=None, headers=None):
            state["requests"].append({"url": url, "json": json, "headers": headers})
            item = state["queue"].pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(gemini_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(gemini_module.time, "sleep", lambda _seconds: None)
    return state


def client(**kwargs) -> GeminiClient:
    kwargs.setdefault("max_retries", 2)
    return GeminiClient(api_key="test-key", model="gemini-test", **kwargs)


def test_the_api_key_travels_in_the_header_not_the_url(transport):
    transport["queue"] = [ok_payload()]

    client().generate_json(template_id="t/v1", system="s", prompt="p", schema=SCHEMA)
    request = transport["requests"][0]

    assert request["headers"]["x-goog-api-key"] == "test-key"
    assert "test-key" not in request["url"]
    assert request["url"].endswith("/models/gemini-test:generateContent")


def test_a_rate_limit_is_retried_then_succeeds(transport):
    transport["queue"] = [FakeResponse(429, "quota"), ok_payload()]

    result = client().generate_json(template_id="t/v1", system="s", prompt="p", schema=SCHEMA)

    assert result.data == {"ok": True}
    assert len(transport["requests"]) == 2


def test_retries_are_bounded_and_report_the_cause(transport):
    transport["queue"] = [FakeResponse(503, "unavailable")] * 3

    with pytest.raises(GeminiError, match="failed after retries"):
        client(max_retries=2).generate_json(
            template_id="t/v1", system="s", prompt="p", schema=SCHEMA
        )
    assert len(transport["requests"]) == 3


def test_an_auth_failure_is_not_retried(transport):
    transport["queue"] = [FakeResponse(401, "API key not valid")]

    with pytest.raises(GeminiError, match="401"):
        client().generate_json(template_id="t/v1", system="s", prompt="p", schema=SCHEMA)
    assert len(transport["requests"]) == 1


def test_a_network_error_is_retried(transport):
    transport["queue"] = [httpx.ConnectError("dns"), ok_payload()]

    result = client().generate_json(template_id="t/v1", system="s", prompt="p", schema=SCHEMA)

    assert result.data == {"ok": True}


def test_a_model_rejecting_thinking_config_is_retried_without_it(transport):
    transport["queue"] = [
        FakeResponse(400, "thinkingConfig is not supported for this model"),
        ok_payload(),
    ]

    result = client(thinking_budget=0).generate_json(
        template_id="t/v1", system="s", prompt="p", schema=SCHEMA
    )

    assert result.data == {"ok": True}
    assert "thinkingConfig" in transport["requests"][0]["json"]["generationConfig"]
    assert "thinkingConfig" not in transport["requests"][1]["json"]["generationConfig"]


def test_a_negative_thinking_budget_omits_the_field_entirely(transport):
    transport["queue"] = [ok_payload()]

    client(thinking_budget=-1).generate_json(
        template_id="t/v1", system="s", prompt="p", schema=SCHEMA
    )

    assert "thinkingConfig" not in transport["requests"][0]["json"]["generationConfig"]


def test_the_factory_wires_the_copilot_only_when_a_key_exists():
    without = Settings(_env_file=None, gemini_api_key="")
    with_key = Settings(_env_file=None, gemini_api_key="test-key")

    plain = build_coding_agent(without, build_gemini_client(without))
    assisted = build_coding_agent(with_key, build_gemini_client(with_key))

    assert isinstance(plain, ReviewedCodingAgent)
    assert isinstance(assisted, GeminiCodingAgent)
    assert assisted.assist_mode is AssistMode.AUTO
    assert assisted.available is True
