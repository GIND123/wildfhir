import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from aquafhir.models import Coding, MappingProposal, RawReading


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class ReviewedCodingAgent:
    """Deterministic, auditable baseline for an eventual model-backed coding agent.

    Any future LLM adapter should return the same MappingProposal contract. It must
    not publish FHIR resources directly; publication happens only after approval.
    """

    def __init__(self, rules_path: Path, review_threshold: float = 0.9) -> None:
        document = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        self.system: str = document["system"]
        self.rules: list[dict[str, Any]] = document["rules"]
        self.review_threshold = review_threshold

    def propose(self, reading: RawReading) -> MappingProposal:
        query = _normalize(reading.parameter)
        ranked: list[tuple[float, dict[str, Any], str]] = []
        for rule in self.rules:
            for alias in rule["aliases"]:
                normalized_alias = _normalize(alias)
                score = 1.0 if query == normalized_alias else SequenceMatcher(
                    None, query, normalized_alias
                ).ratio()
                ranked.append((score, rule, alias))

        score, rule, alias = max(ranked, key=lambda item: item[0])
        coding = None
        normalized_value = None
        normalized_unit = None
        rationale = "No sufficiently close curated terminology match."

        if score >= 0.65:
            coding = Coding(system=self.system, code=rule["code"], display=rule["display"])
            normalized_value, normalized_unit, unit_note = self._normalize_unit(reading, rule)
            if normalized_unit is None:
                score = min(score, 0.69)
            rationale = f"Matched input to curated alias '{alias}'. {unit_note}"

        confidence = round(min(score, 0.99), 2)
        return MappingProposal(
            id=str(uuid4()),
            reading=reading,
            coding=coding,
            normalized_value=normalized_value,
            normalized_unit=normalized_unit,
            confidence=confidence,
            rationale=rationale,
            requires_review=True,
        )

    @staticmethod
    def _normalize_unit(
        reading: RawReading, rule: dict[str, Any]
    ) -> tuple[float | None, str | None, str]:
        if reading.unit in rule.get("accepted_units", []):
            return reading.value, reading.unit, "Unit is an accepted UCUM code."
        conversion = rule.get("unit_conversions", {}).get(reading.unit)
        if conversion:
            value = reading.value * float(conversion["factor"])
            return value, conversion["target"], f"Converted from {reading.unit}."
        return None, None, f"Unit '{reading.unit}' needs reviewer correction."

