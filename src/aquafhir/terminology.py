"""Turns a curated OAH display term into candidate real-world codes.

This is deliberately the smallest possible bridge between the project's
temporary OAH code system and the terminology stack the standards judges will
actually recognise: real LOINC and SNOMED CT codes, never invented by hand.

Two sources, in order of precision:

1. **The published LOINC table, scoped to environmental specimens.** This is the
   high-confidence path and it needs no network and no key. LOINC already
   carries ``9481-3`` pH of Water and ``12530-2`` Chloride in Water; a search
   scoped to Water/Air specimens finds them exactly, where a generic clinical
   search cannot.
2. **UMLS UTS search**, to top up whatever the local table does not cover -- in
   particular SNOMED CT, which this repository does not vendor. Its LOINC hits
   are validated against the same published table before being shown.

The guardrail is the same shape as `coding_llm.py`'s: a candidate is only ever
a *suggestion*. `service.approve()` attaches a `secondary_coding` to the
published Observation only when a reviewer explicitly supplies one in the
`ReviewDecision`. This module never writes to FHIR and is never consulted by the
alerting policy.
"""

import logging
import re
from difflib import SequenceMatcher

from aquafhir.loinc_table import LoincTable
from aquafhir.models import TerminologyMatch
from aquafhir.umls import VOCABULARY_SYSTEMS, UMLSClient, UMLSError

logger = logging.getLogger(__name__)

LOINC_VOCABULARY = "LNC"
LOINC_SYSTEM = VOCABULARY_SYSTEMS[LOINC_VOCABULARY]


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class TerminologyCrosswalk:
    def __init__(
        self,
        umls: UMLSClient,
        *,
        vocabularies: tuple[str, ...] = ("LNC", "SNOMEDCT_US"),
        loinc_table: LoincTable | None = None,
    ) -> None:
        self.umls = umls
        self.vocabularies = vocabularies
        self.loinc_table = loinc_table

    @property
    def available(self) -> bool:
        """True when at least one source can answer.

        The local table alone is enough, so the crosswalk keeps working with no
        UMLS key at all.
        """
        return self.umls.enabled or self._local_available

    @property
    def local_available(self) -> bool:
        return self._local_available

    @property
    def _local_available(self) -> bool:
        return self.loinc_table is not None and self.loinc_table.available

    def sources(self) -> list[str]:
        names = []
        if self._local_available:
            names.append("loinc-table")
        if self.umls.enabled:
            names.append("umls")
        return names

    def suggest(self, display: str, limit: int = 5) -> list[TerminologyMatch]:
        """Suggest publishable codes for `display`, best first.

        Local environmental LOINC hits rank first; UMLS tops up the remainder.
        A UMLS outage degrades to the local results rather than failing, but a
        UMLS failure with no local results is surfaced so the reviewer is not
        silently told "no match" when the real answer is "lookup broke".
        """
        matches = self._local_matches(display, limit)
        if len(matches) >= limit or not self.umls.enabled:
            return matches[:limit]

        seen = {(match.system, match.code) for match in matches}
        try:
            remote = self._umls_matches(display, limit)
        except UMLSError:
            if matches:
                logger.warning("UMLS lookup failed; returning local LOINC matches only")
                return matches[:limit]
            raise
        matches.extend(
            match for match in remote if (match.system, match.code) not in seen
        )
        return matches[:limit]

    # -- sources -----------------------------------------------------------

    def _local_matches(self, display: str, limit: int) -> list[TerminologyMatch]:
        if not self._local_available or LOINC_VOCABULARY not in self.vocabularies:
            return []
        assert self.loinc_table is not None
        return [
            TerminologyMatch(
                system=LOINC_SYSTEM,
                code=entry.code,
                display=entry.long_common_name,
                vocabulary=LOINC_VOCABULARY,
                score=round(score, 2),
            )
            for score, entry in self.loinc_table.search(display, limit=limit)
        ]

    def _umls_matches(self, display: str, limit: int) -> list[TerminologyMatch]:
        """Rank UMLS matches by closeness to the query term.

        Only vocabularies in `self.vocabularies` are ever surfaced, re-checked
        here regardless of what the `sabs` search filter already requested --
        the same "a request is not a proof" posture the Gemini catalog re-check
        in `coding_llm.py` uses.
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
            if not self._is_publishable(match.root_source, match.code):
                logger.info(
                    "Dropped %s candidate %r: not a published LOINC term code",
                    match.root_source,
                    match.code,
                )
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

    def _is_publishable(self, vocabulary: str, code: str) -> bool:
        """Reject codes that cannot be published under their claimed system.

        Only LOINC is checkable offline here. A SNOMED CT concept id is passed
        through -- validating it would need the SNOMED release, which this
        repository deliberately does not vendor.
        """
        if vocabulary != LOINC_VOCABULARY:
            return True
        if not self._local_available:
            return True
        assert self.loinc_table is not None
        return self.loinc_table.contains(code)
