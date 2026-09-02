"""Minimal GBIF Backbone Taxonomy client.

The bridge uses GBIF only to *suggest* a taxonomic identity for an organism
named in a source label, exactly the way `umls.py` is used only to suggest a
LOINC/SNOMED CT crosswalk. The same non-negotiables hold: it returns
candidates, never selects one, never mutates FHIR state, and never influences
an alert decision. A reviewer attaches a taxon explicitly at approval time
(see `ReviewDecision.taxon` in `models.py`).

Two things about this API drive the guardrails below.

**`matchType` is the only trustworthy signal.** A refusal comes back as
``{"confidence": 100, "matchType": "NONE"}`` -- a *full* confidence score
attached to a non-answer. Branching on `confidence` would therefore accept
every miss. This module keys on `matchType` and treats `confidence` as
display-only metadata.

**Unlike a clinical Metathesaurus search, GBIF declines cleanly.** Asking UMLS
for ``pH`` returns *Peliosis hepatis*; asking GBIF for ``pH``, ``dissolved
oxygen``, ``chloride`` or ``Leitfähigkeit`` returns `NONE` every time. That is
what makes it safe to run this over raw, uncurated source labels.

Read-only calls need no key and no registration
(https://techdocs.gbif.org/en/openapi/). The service rate-limits with HTTP 429
under load, which the shared retry path already treats as transient.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_API_BASE = "https://api.gbif.org/v1"

# There is no HL7-registered code system URI for GBIF taxon keys. The DOI of
# the GBIF Backbone Taxonomy identifies the checklist these keys belong to, so
# it is the most precise identifier available and is what this project
# publishes. Recorded as a deliberate project choice, not a registered system.
GBIF_SYSTEM = "https://doi.org/10.15468/39omei"
GBIF_VOCABULARY = "GBIF"

# A usable identification only. `NONE` is a refusal; `HIGHERRANK` means GBIF
# could not get below kingdom/phylum and is too coarse to publish as an
# identification.
ACCEPTED_MATCH_TYPES = frozenset({"EXACT", "FUZZY"})

_RANKS = ("kingdom", "phylum", "class", "order", "family", "genus", "species")


class GbifError(RuntimeError):
    """Any failure to obtain a usable response from the GBIF API."""


@dataclass(frozen=True)
class GbifMatch:
    """One accepted taxon match.

    `usage_key` is the GBIF Backbone key and is what becomes `Coding.code`.
    Where GBIF reports the queried name as a synonym it also returns the
    accepted key; `usage_key` always holds the key a reviewer should publish.
    """

    usage_key: int
    scientific_name: str
    canonical_name: str
    rank: str
    status: str
    match_type: str
    confidence: int
    synonym: bool = False
    classification: dict[str, str] = field(default_factory=dict)

    @property
    def lineage(self) -> str:
        """Kingdom to genus, for a reviewer deciding if this is the right organism."""
        return " > ".join(
            self.classification[rank] for rank in _RANKS if self.classification.get(rank)
        )


class GbifClient:
    def __init__(
        self,
        *,
        enabled: bool = True,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 15.0,
        max_retries: int = 2,
    ) -> None:
        self._enabled = enabled
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)

    @property
    def enabled(self) -> bool:
        """No key exists to be missing, so this is purely a configuration switch."""
        return self._enabled

    def match(self, name: str) -> GbifMatch | None:
        """Resolve `name` to a Backbone taxon, or None when GBIF declines.

        Returning None is a real answer: it is what every non-organism label
        produces, and it is the reason this can be run over raw source text.
        """
        if not self.enabled:
            raise GbifError("GBIF lookups are disabled (GBIF_ENABLED=false)")
        cleaned = name.strip()
        if not cleaned:
            return None
        payload = self._get_with_retries(
            "/species/match", {"name": cleaned, "verbose": "false", "strict": "false"}
        )
        return self._to_match(payload)

    @staticmethod
    def _to_match(payload: dict[str, Any]) -> GbifMatch | None:
        # Deliberately never reads `confidence` to decide. A refusal carries
        # confidence 100, so trusting it would accept every miss.
        if payload.get("matchType") not in ACCEPTED_MATCH_TYPES:
            return None
        # A synonym match names the accepted taxon separately; publish that one.
        key = payload.get("acceptedUsageKey") or payload.get("usageKey")
        rank = payload.get("rank")
        if not isinstance(key, int) or not isinstance(rank, str) or not rank:
            return None
        name = payload.get("acceptedScientificName") or payload.get("scientificName")
        if not isinstance(name, str) or not name:
            return None
        confidence = payload.get("confidence")
        return GbifMatch(
            usage_key=key,
            scientific_name=name,
            canonical_name=str(payload.get("canonicalName") or name),
            rank=rank,
            status=str(payload.get("status") or "UNKNOWN"),
            match_type=str(payload["matchType"]),
            confidence=confidence if isinstance(confidence, int) else 0,
            synonym=bool(payload.get("synonym")),
            classification={
                level: str(payload[level])
                for level in _RANKS
                if isinstance(payload.get(level), str)
            },
        )

    # -- transport ---------------------------------------------------------

    def _get_with_retries(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self.api_base}{path}"
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(url, params=params)
                if response.status_code in {408, 429, 500, 502, 503, 504}:
                    raise GbifError(
                        f"GBIF transient error {response.status_code}: {response.text[:300]}"
                    )
                if response.status_code >= 400:
                    raise GbifError(
                        f"GBIF request failed {response.status_code}: {response.text[:300]}"
                    )
                body = response.json()
                if not isinstance(body, dict):
                    raise GbifError("GBIF returned a non-object response")
                return body
            except (httpx.HTTPError, GbifError) as error:
                last_error = error
                if isinstance(error, GbifError) and "transient" not in str(error):
                    raise
                if attempt == self.max_retries:
                    break
                time.sleep(0.6 * (2**attempt))

        raise GbifError(f"GBIF call failed after retries: {last_error}")
