"""The published LOINC term table: validation, and environmental-specimen search.

This module does two jobs, both grounded in the licensed ``LoincTableCore``
artifact rather than in a remote service.

**Validation.** UMLS search with ``sabs=LNC`` does not only return published
LOINC term codes. It also returns LOINC *Parts* (``LP14752-7``) and
Metathesaurus-generated identifiers (``MTHU001949``) minted where a concept has
no source-asserted code. Neither is a LOINC observation code, and publishing one
as ``Coding.code`` under ``system = http://loinc.org`` asserts a code that does
not exist. A reviewer cannot be expected to know that by sight, so the check is
code's job.

**Search.** A generic UMLS Metathesaurus query is a clinical search, and it
ranks accordingly: asking it for ``pH`` returns *Peliosis hepatis* well above
*pH of Water*, because nothing in the query says "this is a river". But LOINC
itself carries the right answers -- ``9481-3`` pH of Water, ``12530-2`` Chloride
in Water, ``87444-6`` Electron [Electrical Conductivity] of Water -- and they
are trivially findable once the search is scoped to environmental specimens.
Searching the table locally is therefore both more precise *and* cheaper than a
network round trip.

Semantic fitness stays the reviewer's job either way. This module only ensures
the candidates put in front of them are real, publishable, environmental LOINC
codes.

Per the LOINC license the artifact's fields are never altered; it is read only.
"""

import csv
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import cached_property
from pathlib import Path

logger = logging.getLogger(__name__)

CODE_COLUMN = "LOINC_NUM"

# Exact SYSTEM values denoting an environmental specimen. Deliberately an
# allowlist and not a substring test: LOINC's "Airway adaptor",
# "Airway.proximal", and friends are respiratory-device systems, not air quality.
ENVIRONMENTAL_SYSTEMS = frozenset({"Water", "Air", "Envir", "Environmental specimen"})

# Below this a candidate is noise rather than a suggestion. Tuned against the
# real table so that near-miss analytes are excluded -- "Dissolved solids" for a
# dissolved-oxygen query, "Wind chill temperature" for a water-temperature one.
# Showing nothing correctly signals "environmental LOINC does not cover this";
# showing a plausible-looking wrong code just spends reviewer attention.
MIN_SCORE = 0.7

# Whole-name token overlap is strong evidence but weaker than an exact analyte
# match, so it is discounted before the two are compared.
CONTAINMENT_WEIGHT = 0.85


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _tokens(value: str) -> set[str]:
    return set(_normalize(value).split())


@dataclass(frozen=True)
class LoincEntry:
    code: str
    component: str
    system: str
    long_common_name: str


class LoincTable:
    """Lazily-loaded published LOINC terms, for validation and local search.

    A missing or unreadable table is a degradation, not an outage: validation
    stops filtering and local search returns nothing, both with a warning, and
    the UMLS path keeps working. That matches how every other optional
    dependency in this bridge behaves.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @cached_property
    def _loaded(self) -> tuple[frozenset[str], tuple[LoincEntry, ...]]:
        if not self.path.exists():
            logger.warning(
                "LOINC table not found at %s; suggested LOINC codes will not be "
                "validated and local LOINC search is unavailable",
                self.path,
            )
            return frozenset(), ()
        try:
            with self.path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None or CODE_COLUMN not in reader.fieldnames:
                    logger.warning(
                        "LOINC table at %s has no %s column; skipping validation",
                        self.path,
                        CODE_COLUMN,
                    )
                    return frozenset(), ()
                codes: set[str] = set()
                entries: list[LoincEntry] = []
                for row in reader:
                    code = (row.get(CODE_COLUMN) or "").strip()
                    if not code:
                        continue
                    codes.add(code)
                    # Only ACTIVE terms are ever suggested; a deprecated code
                    # still validates, because it was legitimately published.
                    if (row.get("STATUS") or "").strip().upper() != "ACTIVE":
                        continue
                    if (row.get("SYSTEM") or "").strip() not in ENVIRONMENTAL_SYSTEMS:
                        continue
                    entries.append(
                        LoincEntry(
                            code=code,
                            component=(row.get("COMPONENT") or "").strip(),
                            system=(row.get("SYSTEM") or "").strip(),
                            long_common_name=(row.get("LONG_COMMON_NAME") or "").strip(),
                        )
                    )
        except OSError as error:
            logger.warning("Could not read the LOINC table at %s: %s", self.path, error)
            return frozenset(), ()

        logger.info(
            "Loaded %d published LOINC codes from %s (%d environmental terms searchable)",
            len(codes),
            self.path,
            len(entries),
        )
        return frozenset(codes), tuple(entries)

    @property
    def codes(self) -> frozenset[str]:
        return self._loaded[0]

    @property
    def environmental_entries(self) -> tuple[LoincEntry, ...]:
        return self._loaded[1]

    @property
    def available(self) -> bool:
        return bool(self.codes)

    def contains(self, code: str) -> bool:
        return code.strip() in self.codes

    def search(self, term: str, limit: int = 5) -> list[tuple[float, LoincEntry]]:
        """Rank environmental LOINC terms against a query, best first."""
        query = _normalize(term)
        if not query:
            return []
        query_tokens = _tokens(term)
        scored: list[tuple[float, LoincEntry]] = []
        for entry in self.environmental_entries:
            score = self._score(query, query_tokens, entry)
            if score >= MIN_SCORE:
                scored.append((score, entry))
        scored.sort(key=lambda item: (-item[0], item[1].code))
        return scored[:limit]

    @staticmethod
    def _score(query: str, query_tokens: set[str], entry: LoincEntry) -> float:
        component = _normalize(entry.component)
        if component and component == query:
            return 1.0
        component_ratio = SequenceMatcher(None, query, component).ratio() if component else 0.0
        name_tokens = _tokens(entry.long_common_name)
        containment = (
            len(query_tokens & name_tokens) / len(query_tokens) if query_tokens else 0.0
        )
        return max(component_ratio, containment * CONTAINMENT_WEIGHT)
