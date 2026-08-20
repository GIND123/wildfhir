"""Turns a curated OAH display term into candidate real-world codes.

This is deliberately the smallest possible bridge between the project's
temporary OAH code system and the terminology stack the standards judges will
actually recognise: real LOINC and SNOMED CT codes, resolved through the NLM
UMLS Metathesaurus rather than invented by hand.

The guardrail is the same shape as `coding_llm.py`'s: a candidate is only
ever a *suggestion*. `service.approve()` only attaches a `secondary_coding`
to the published Observation when a reviewer explicitly supplies one in the
`ReviewDecision` -- this module never writes to FHIR and is never consulted
by the alerting policy.
"""

import re
from difflib import SequenceMatcher

from aquafhir.models import TerminologyMatch
from aquafhir.umls import VOCABULARY_SYSTEMS, UMLSClient


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class TerminologyCrosswalk:
    def __init__(
        self,
        umls: UMLSClient,
        *,
        vocabularies: tuple[str, ...] = ("LNC", "SNOMEDCT_US"),
    ) -> None:
        self.umls = umls
        self.vocabularies = vocabularies

    @property
    def available(self) -> bool:
        return self.umls.enabled

    def suggest(self, display: str, limit: int = 5) -> list[TerminologyMatch]:
        """Rank UMLS matches for `display` by closeness to the query term.

        Only vocabularies in `self.vocabularies` are ever surfaced, re-checked
        here regardless of what the `sabs` search filter already requested --
        the same "a request is not a proof" posture the Gemini catalog
        re-check in `coding_llm.py` uses.
        """
        raw = self.umls.search(display, vocabularies=self.vocabularies, limit=limit * 3)
        query = _normalize(display)
        scored: list[tuple[float, TerminologyMatch]] = []
        for match in raw:
            if match.root_source not in self.vocabularies:
                continue
            system = VOCABULARY_SYSTEMS.get(match.root_source)
            if not system:
                continue
            score = SequenceMatcher(None, query, _normalize(match.name)).ratio()
            scored.append(
                (
                    score,
                    TerminologyMatch(
                        system=system,
                        code=match.code,
                        display=match.name,
                        vocabulary=match.root_source,
                        score=round(score, 2),
                    ),
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]
