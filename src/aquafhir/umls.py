"""Minimal UMLS Terminology Services (UTS) REST client.

The bridge uses UMLS only to *suggest* a real LOINC/SNOMED CT crosswalk for a
curated OAH code, exactly the way `gemini.py` is used only to suggest a
terminology mapping. The same non-negotiables hold:

1. It only ever returns candidates. It never selects the published coding,
   never mutates FHIR state, and never changes an alert decision. A reviewer
   must explicitly attach one at approval time (see
   `ReviewDecision.secondary_coding` in `models.py`).
2. Authentication follows the officially documented UTS REST API scheme: a
   single ``apiKey`` query parameter issued from the caller's UTS profile
   (https://documentation.uts.nlm.nih.gov/rest/authentication.html). NLM
   deprecated the older ticket-granting-ticket flow, and there is no OAuth2
   client-credentials grant for this API as of 2026 -- a client_id/secret
   pair from anywhere else does not work here.
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_API_BASE = "https://uts-ws.nlm.nih.gov/rest"

# UMLS root-source abbreviation -> canonical FHIR coding system URI.
VOCABULARY_SYSTEMS: dict[str, str] = {
    "LNC": "http://loinc.org",
    "SNOMEDCT_US": "http://snomed.info/sct",
}


class UMLSError(RuntimeError):
    """Any failure to obtain a usable response from the UMLS UTS API."""


class UMLSDisabledError(UMLSError):
    """Raised when a terminology feature is used without UMLS_API_KEY configured."""


@dataclass(frozen=True)
class UMLSMatch:
    """One raw UTS search result.

    With ``returnIdType=code`` the UTS search API returns the *source
    vocabulary* code (e.g. a LOINC number or a SNOMED CT concept id) in
    ``code``, not the UMLS CUI -- that is exactly what a FHIR ``Coding.code``
    needs, so the crosswalk layer never has to make a second call to resolve
    it.
    """

    code: str
    root_source: str
    name: str
    uri: str


class UMLSClient:
    def __init__(
        self,
        api_key: str,
        *,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 15.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key.strip()
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(
        self,
        term: str,
        *,
        vocabularies: tuple[str, ...] = ("LNC", "SNOMEDCT_US"),
        limit: int = 5,
    ) -> list[UMLSMatch]:
        """Search the UTS Metathesaurus for concepts matching ``term``."""
        if not self.enabled:
            raise UMLSDisabledError(
                "UMLS_API_KEY is not configured; terminology crosswalk is unavailable"
            )
        params = {
            "apiKey": self.api_key,
            "string": term,
            "sabs": ",".join(vocabularies),
            "returnIdType": "code",
            "searchType": "words",
            "pageSize": str(max(1, limit)),
        }
        payload = self._get_with_retries("/search/current", params)
        results = payload.get("result", {}).get("results", [])
        matches = [
            UMLSMatch(
                code=str(item.get("ui", "")),
                root_source=str(item.get("rootSource", "")),
                name=str(item.get("name", "")),
                uri=str(item.get("uri", "")),
            )
            for item in results
            if item.get("ui") and item.get("ui") != "NONE"
        ]
        return matches[:limit]

    # -- transport ---------------------------------------------------------

    def _get_with_retries(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self.api_base}{path}"
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(url, params=params)
                if response.status_code in {408, 429, 500, 502, 503, 504}:
                    raise UMLSError(
                        f"UMLS transient error {response.status_code}: {response.text[:300]}"
                    )
                if response.status_code >= 400:
                    raise UMLSError(
                        f"UMLS request failed {response.status_code}: {response.text[:300]}"
                    )
                return response.json()
            except (httpx.HTTPError, UMLSError) as error:
                last_error = error
                if isinstance(error, UMLSError) and "transient" not in str(error):
                    raise
                if attempt == self.max_retries:
                    break
                time.sleep(0.6 * (2**attempt))

        raise UMLSError(f"UMLS call failed after retries: {last_error}")
