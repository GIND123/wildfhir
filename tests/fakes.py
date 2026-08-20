"""Test doubles that keep the whole suite offline.

`FakeGemini` overrides only the HTTP hop, so every test still exercises the real
schema construction, JSON parsing, hashing, and guardrail code in
`gemini.py`, `coding_llm.py`, `intake.py`, and `briefing.py`.
"""

import json
from typing import Any

from aquafhir.gemini import GeminiClient, GeminiError


class FakeGemini(GeminiClient):
    def __init__(self, responses: list[Any] | None = None, *, api_key: str = "test-key") -> None:
        super().__init__(api_key=api_key, model="gemini-test", max_retries=0)
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def _post_with_retries(self, body: dict[str, Any]) -> str:
        self.calls.append(body)
        if not self.responses:
            raise GeminiError("FakeGemini has no queued response")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)

    @property
    def last_prompt(self) -> str:
        return self.calls[-1]["contents"][0]["parts"][0]["text"]

    @property
    def last_schema(self) -> dict[str, Any]:
        return self.calls[-1]["generationConfig"]["responseSchema"]


class BrokenGemini(GeminiClient):
    """Enabled by configuration but always failing upstream."""

    def __init__(self) -> None:
        super().__init__(api_key="test-key", model="gemini-test", max_retries=0)

    def _post_with_retries(self, body: dict[str, Any]) -> str:
        raise GeminiError("simulated upstream outage")
