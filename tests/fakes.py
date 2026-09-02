"""Test doubles that keep the whole suite offline.

`FakeGemini` and `FakeUMLS` override only the HTTP hop, so every test still
exercises the real schema construction, JSON parsing, hashing, and guardrail
code in `gemini.py`, `coding_llm.py`, `intake.py`, `briefing.py`, `umls.py`,
and `terminology.py`.
"""

import json
from typing import Any

from aquafhir.gbif import GbifClient, GbifError
from aquafhir.gemini import GeminiClient, GeminiError
from aquafhir.umls import UMLSClient, UMLSError


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


class FakeUMLS(UMLSClient):
    def __init__(
        self, responses: list[Any] | None = None, *, api_key: str = "test-key"
    ) -> None:
        super().__init__(api_key=api_key, max_retries=0)
        self.responses = list(responses or [])
        self.calls: list[dict[str, str]] = []

    def _get_with_retries(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        self.calls.append(params)
        if not self.responses:
            raise UMLSError("FakeUMLS has no queued response")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class BrokenUMLS(UMLSClient):
    """Enabled by configuration but always failing upstream."""

    def __init__(self) -> None:
        super().__init__(api_key="test-key", max_retries=0)

    def _get_with_retries(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        raise UMLSError("simulated upstream outage")


class FakeGbif(GbifClient):
    """Queued GBIF payloads with the HTTP hop removed.

    Responses are the raw JSON bodies the API returns, so `_to_match` and every
    guardrail in it still run for real -- including the one that must ignore
    the `confidence: 100` that GBIF attaches to a refusal.
    """

    def __init__(self, responses: list[Any] | None = None, *, enabled: bool = True) -> None:
        super().__init__(enabled=enabled, max_retries=0)
        self.responses = list(responses or [])
        self.calls: list[dict[str, str]] = []

    def _get_with_retries(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        self.calls.append(params)
        if not self.responses:
            return {"matchType": "NONE", "confidence": 100, "synonym": False}
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class BrokenGbif(GbifClient):
    """Enabled by configuration but always failing upstream."""

    def __init__(self) -> None:
        super().__init__(enabled=True, max_retries=0)

    def _get_with_retries(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        raise GbifError("simulated upstream outage")
