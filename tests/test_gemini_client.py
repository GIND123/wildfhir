import json

import pytest

from aquafhir.gemini import GeminiClient, GeminiDisabledError, GeminiError, _strip_code_fence
from tests.fakes import FakeGemini

SCHEMA = {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}, "required": ["ok"]}


def test_missing_key_disables_the_client():
    client = GeminiClient(api_key="  ", model="gemini-test")

    assert client.enabled is False
    with pytest.raises(GeminiDisabledError):
        client.generate_json(template_id="t/v1", system="s", prompt="p", schema=SCHEMA)


def test_structured_call_records_prompt_and_response_hashes():
    client = FakeGemini([{"ok": True}])

    result = client.generate_json(template_id="t/v1", system="sys", prompt="body", schema=SCHEMA)

    assert result.data == {"ok": True}
    assert result.template_id == "t/v1"
    assert len(result.prompt_hash) == 64
    assert len(result.response_hash) == 64
    assert result.latency_ms >= 0


def test_prompt_hash_changes_with_the_template_version():
    first = FakeGemini([{"ok": True}]).generate_json(
        template_id="t/v1", system="sys", prompt="body", schema=SCHEMA
    )
    second = FakeGemini([{"ok": True}]).generate_json(
        template_id="t/v2", system="sys", prompt="body", schema=SCHEMA
    )

    assert first.prompt_hash != second.prompt_hash


def test_request_sets_json_mode_and_zero_temperature():
    client = FakeGemini([{"ok": True}])
    client.generate_json(template_id="t/v1", system="sys", prompt="body", schema=SCHEMA)

    config = client.calls[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["temperature"] == 0.0
    assert config["responseSchema"] == SCHEMA


def test_non_json_response_is_an_error_not_a_crash():
    client = FakeGemini(["I cannot answer that."])

    with pytest.raises(GeminiError, match="non-JSON"):
        client.generate_json(template_id="t/v1", system="s", prompt="p", schema=SCHEMA)


def test_markdown_fenced_json_is_recovered():
    assert json.loads(_strip_code_fence('```json\n{"ok": true}\n```')) == {"ok": True}


def test_blocked_prompt_is_surfaced_clearly():
    with pytest.raises(GeminiError, match="blocked"):
        GeminiClient._extract_text({"promptFeedback": {"blockReason": "SAFETY"}})


def test_truncated_response_is_rejected_rather_than_parsed():
    payload = {
        "candidates": [
            {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"ok":'}]}}
        ]
    }

    with pytest.raises(GeminiError, match="truncated"):
        GeminiClient._extract_text(payload)


def test_empty_candidate_list_is_rejected():
    with pytest.raises(GeminiError, match="no candidates"):
        GeminiClient._extract_text({"candidates": []})


def test_thinking_config_is_dropped_on_demand():
    body = {"generationConfig": {"temperature": 0, "thinkingConfig": {"thinkingBudget": 0}}}
    trimmed = GeminiClient._without_thinking_config(body)

    assert "thinkingConfig" not in trimmed["generationConfig"]
    assert "thinkingConfig" in body["generationConfig"]
