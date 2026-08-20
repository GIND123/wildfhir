"""Minimal, dependency-light Gemini client.

The bridge talks to the Generative Language REST API directly with ``httpx``
instead of vendoring an SDK. That keeps the dependency surface auditable, makes
every request shape visible in one file, and lets the whole AI layer fail closed
when no key is configured.

Two invariants hold everywhere this client is used:

1. It only ever returns *proposals* or *narrative*. It never mutates FHIR state,
   never approves a mapping, and never changes an alert decision.
2. Every response is recorded with model id, prompt-template id, and hashes of
   the exact prompt and response, so the provenance chain can prove what the
   model was asked and what it said.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


class GeminiError(RuntimeError):
    """Any failure to obtain a usable structured response from Gemini."""


class GeminiDisabledError(GeminiError):
    """Raised when an AI feature is used without GEMINI_API_KEY configured."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip()


@dataclass(frozen=True)
class GeminiResult:
    """A parsed structured response plus everything provenance needs."""

    data: Any
    model: str
    template_id: str
    prompt_hash: str
    response_hash: str
    latency_ms: int
    raw_text: str


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        api_base: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 30.0,
        max_output_tokens: int = 2048,
        max_retries: int = 2,
        thinking_budget: int = 0,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self.max_retries = max(0, max_retries)
        self.thinking_budget = thinking_budget

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def generate_json(
        self,
        *,
        template_id: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> GeminiResult:
        """Call Gemini with a response schema and return parsed JSON.

        ``template_id`` is a versioned prompt name (for example
        ``coding-proposer/v1``). It is hashed together with the rendered prompt
        so a later audit can tell a prompt change from an input change.
        """
        if not self.enabled:
            raise GeminiDisabledError(
                "GEMINI_API_KEY is not configured; AI assistance is unavailable"
            )

        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "maxOutputTokens": self.max_output_tokens,
                "candidateCount": 1,
            },
        }
        if self.thinking_budget >= 0:
            body["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": self.thinking_budget
            }

        prompt_hash = _sha256(f"{template_id}\n{system}\n{prompt}")
        started = time.perf_counter()
        text = self._post_with_retries(body)
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError as error:
            raise GeminiError(f"Gemini returned non-JSON content: {error}") from error

        return GeminiResult(
            data=data,
            model=self.model,
            template_id=template_id,
            prompt_hash=prompt_hash,
            response_hash=_sha256(text),
            latency_ms=latency_ms,
            raw_text=text,
        )

    # -- transport ---------------------------------------------------------

    def _post_with_retries(self, body: dict[str, Any]) -> str:
        url = f"{self.api_base}/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        payload = body

        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(url, json=payload, headers=headers)
                if response.status_code == 400 and "thinking" in response.text.lower():
                    # Some models reject thinkingConfig outright. Drop it once
                    # rather than failing the whole demo on a config detail.
                    payload = self._without_thinking_config(payload)
                    if payload is not body:
                        body = payload
                        continue
                if response.status_code in {408, 429, 500, 502, 503, 504}:
                    raise GeminiError(
                        f"Gemini transient error {response.status_code}: {response.text[:300]}"
                    )
                if response.status_code >= 400:
                    raise GeminiError(
                        f"Gemini request failed {response.status_code}: {response.text[:300]}"
                    )
                return self._extract_text(response.json())
            except (httpx.HTTPError, GeminiError) as error:
                last_error = error
                if isinstance(error, GeminiError) and "transient" not in str(error):
                    raise
                if attempt == self.max_retries:
                    break
                time.sleep(0.6 * (2**attempt))

        raise GeminiError(f"Gemini call failed after retries: {last_error}")

    @staticmethod
    def _without_thinking_config(body: dict[str, Any]) -> dict[str, Any]:
        if "thinkingConfig" not in body.get("generationConfig", {}):
            return body
        trimmed = json.loads(json.dumps(body))
        trimmed["generationConfig"].pop("thinkingConfig", None)
        return trimmed

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        feedback = payload.get("promptFeedback", {})
        if feedback.get("blockReason"):
            raise GeminiError(f"Gemini blocked the prompt: {feedback['blockReason']}")

        candidates = payload.get("candidates") or []
        if not candidates:
            raise GeminiError("Gemini returned no candidates")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = candidate.get("content", {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise GeminiError(f"Gemini returned an empty candidate (finish: {finish_reason})")
        if finish_reason == "MAX_TOKENS":
            raise GeminiError("Gemini response was truncated; raise GEMINI_MAX_OUTPUT_TOKENS")
        return text
