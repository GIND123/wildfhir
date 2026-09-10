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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx


class GeminiError(RuntimeError):
    """Any failure to obtain a usable structured response from Gemini.

    Carries a short, safe `category` and the HTTP status where one is known,
    so the console can say *why* the AI is degraded without ever showing a
    reviewer the provider's raw error body.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "upstream-error",
        status: int | None = None,
        audit: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status = status
        # Set when the failure happened during a call this client made, so the
        # caller can chain it against the right entity.
        self.audit = audit


def error_category(status: int) -> str:
    """Map an upstream HTTP status onto a category a reviewer can act on."""
    if status == 429:
        return "quota-exceeded"
    if status in {401, 403}:
        return "auth-failed"
    if status == 404:
        # A retired or misspelt model id. Gemini answers 404 for
        # `models/<name>` that no longer exists for this key.
        return "model-not-found"
    if status == 408:
        return "timeout"
    return "upstream-error"


# Failures that mean "this model, for this key", not "Gemini is down". Only
# these justify trying the configured fallback model.
FALLBACK_CATEGORIES = frozenset({"quota-exceeded", "model-not-found"})


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
    # The audit record for exactly this call. Carried with the result rather
    # than parked on the client, so concurrent requests cannot claim each
    # other's records.
    audit: dict[str, Any] = field(default_factory=dict)


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
        fallback_model: str = "",
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        # Tried once when the pinned model answers 429 or 404. A judge's
        # free-tier key has no quota for the preview model; without this the
        # AI layer looked configured and silently failed on every call.
        self.fallback_model = fallback_model.strip() if fallback_model.strip() != model else ""
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self.max_retries = max(0, max_retries)
        self.thinking_budget = thinking_budget
        # Outcome of the last real call, or None if none has been made.
        # Most-recent-call summary for the status endpoint only. Deliberately
        # last-writer-wins: it answers "is the AI working right now", not
        # "what happened in my request". Per-request attribution travels with
        # the result or the error instead.
        self.last_call: dict[str, Any] | None = None

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
        model_used = self.model
        fallback_from: str | None = None
        try:
            try:
                text = self._post_with_retries(body)
            except GeminiError as primary:
                category = getattr(primary, "category", "upstream-error")
                if not self.fallback_model or category not in FALLBACK_CATEGORIES:
                    raise
                # The pinned model is unusable for this key. Try the fallback
                # once and say so in the record: the model that answered is
                # what gets attributed, never the pinned name.
                model_used = self.fallback_model
                fallback_from = self.model
                text = self._send(body, self.fallback_model)
        except GeminiError as error:
            # A key being present says nothing about whether calls succeed.
            # Record what actually happened so status can be honest about it.
            error.audit = self._note(
                outcome="error",
                template_id=template_id,
                prompt_hash=prompt_hash,
                latency_ms=int((time.perf_counter() - started) * 1000),
                category=getattr(error, "category", "upstream-error"),
                status=getattr(error, "status", None),
                model=model_used,
                fallback_from=fallback_from,
            )
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)

        # Recorded only once the payload is usable. Marking the call "ok" the
        # moment bytes arrived counted unparseable and out-of-catalog answers as
        # successes, which is precisely the failure mode status is meant to show.
        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError as error:
            raise GeminiError(
                f"Gemini returned non-JSON content: {error}",
                category="invalid-json",
                audit=self._note(
                    outcome="error", template_id=template_id, prompt_hash=prompt_hash,
                    latency_ms=latency_ms, category="invalid-json",
                    model=model_used, fallback_from=fallback_from,
                ),
            ) from error
        audit = self._note(
            outcome="ok", template_id=template_id, prompt_hash=prompt_hash,
            latency_ms=latency_ms, model=model_used, fallback_from=fallback_from,
        )

        return GeminiResult(
            data=data,
            model=model_used,
            template_id=template_id,
            prompt_hash=prompt_hash,
            response_hash=_sha256(text),
            latency_ms=latency_ms,
            raw_text=text,
            audit=audit,
        )

    def _note(
        self,
        *,
        outcome: str,
        template_id: str,
        latency_ms: int,
        prompt_hash: str | None = None,
        category: str | None = None,
        status: int | None = None,
        model: str | None = None,
        fallback_from: str | None = None,
    ) -> dict[str, Any]:
        """Build the audit record for one call and return it to the caller.

        Deliberately holds no key, no prompt text and no provider error body:
        only the prompt *hash*, a short category, and the HTTP status. That is
        enough for an auditor to correlate a call with its inputs without the
        audit trail becoming a place secrets accumulate.
        """
        record = {
            "operation": template_id.split("/")[0],
            "outcome": outcome,
            "category": category,
            "http_status": status,
            "provider": "google-gemini",
            "model": model or self.model,
            # Set when the pinned model failed and the fallback answered.
            "fallback_from": fallback_from,
            "template_id": template_id,
            "prompt_hash": prompt_hash,
            "latency_ms": latency_ms,
            "at": datetime.now(UTC).isoformat(),
        }
        self.last_call = record
        return record

    # -- transport ---------------------------------------------------------

    def _post_with_retries(self, body: dict[str, Any]) -> str:
        """The pinned model's transport. Test doubles override exactly this."""
        return self._send(body, self.model)

    def _send(self, body: dict[str, Any], model: str) -> str:
        url = f"{self.api_base}/models/{model}:generateContent"
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
                        f"Gemini transient error {response.status_code}: {response.text[:300]}",
                        category=error_category(response.status_code),
                        status=response.status_code,
                    )
                if response.status_code >= 400:
                    raise GeminiError(
                        f"Gemini request failed {response.status_code}: {response.text[:300]}",
                        category=error_category(response.status_code),
                        status=response.status_code,
                    )
                return self._extract_text(response.json())
            except (httpx.HTTPError, GeminiError) as error:
                last_error = error
                if isinstance(error, GeminiError) and "transient" not in str(error):
                    raise
                if attempt == self.max_retries:
                    break
                time.sleep(0.6 * (2**attempt))

        # Carry the cause forward. Re-raising a bare GeminiError here discarded
        # the category, so an exhausted quota surfaced as a generic upstream
        # error and the console could not tell a reviewer what to do about it.
        raise GeminiError(
            f"Gemini call failed after retries: {last_error}",
            category=getattr(last_error, "category", "upstream-error"),
            status=getattr(last_error, "status", None),
        )

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
            raise GeminiError(
                f"Gemini blocked the prompt: {feedback['blockReason']}", category="blocked"
            )

        candidates = payload.get("candidates") or []
        if not candidates:
            raise GeminiError("Gemini returned no candidates", category="empty-response")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = candidate.get("content", {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise GeminiError(
                f"Gemini returned an empty candidate (finish: {finish_reason})",
                category="empty-response",
            )
        if finish_reason == "MAX_TOKENS":
            raise GeminiError(
                "Gemini response was truncated; raise GEMINI_MAX_OUTPUT_TOKENS",
                category="truncated",
            )
        return text


SAFE_MESSAGES = {
    "quota-exceeded": "Gemini quota exceeded. The deterministic pipeline is unaffected.",
    "model-not-found": "The configured Gemini model is not available to this key.",
    "auth-failed": "Gemini rejected the configured credentials.",
    "timeout": "Gemini did not respond in time.",
    "blocked": "Gemini declined to answer this prompt.",
    "truncated": "Gemini's answer was cut off before it was complete.",
    "empty-response": "Gemini returned no usable answer.",
    "invalid-json": "Gemini returned a malformed answer.",
    "invalid-response": "Gemini's answer did not match the expected shape.",
    "out-of-catalog": "Gemini proposed a code outside the curated catalog.",
    "upstream-error": "Gemini could not be reached.",
}


def safe_message(error: GeminiError) -> str:
    """A message fit to leave the process.

    The exception text carries up to 300 characters of the provider's own
    response body. That belongs in the server log, not in an HTTP response or
    a reviewer's toast.
    """
    category = getattr(error, "category", "upstream-error")
    message = SAFE_MESSAGES.get(category, SAFE_MESSAGES["upstream-error"])
    status = getattr(error, "status", None)
    return f"{message} (category: {category}{f', HTTP {status}' if status else ''})"


def mark_degraded(record: dict[str, Any] | None, category: str) -> dict[str, Any] | None:
    """Downgrade one call's record after a feature rejected its answer.

    A response can parse and still be unusable: a code outside the curated
    catalog, or a payload that is not the object the feature expected. The
    transport succeeded, so only the feature layer knows this happened. Takes
    the record explicitly, because mutating "the last call" would corrupt a
    concurrent request's record.
    """
    if record is not None and record.get("outcome") == "ok":
        record["outcome"] = "rejected"
        record["category"] = category
    return record
