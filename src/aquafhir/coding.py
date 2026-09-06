import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import yaml

from aquafhir.models import (
    CandidateCoding,
    Coding,
    MappingProposal,
    ProposerKind,
    RawReading,
)

MATCH_FLOOR = 0.65
UNRESOLVED_UNIT_CEILING = 0.69


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class CodingProposer(Protocol):
    """The single contract every proposer must satisfy.

    A model-backed proposer is interchangeable with the curated one precisely
    because it may only return a `MappingProposal` — a *request* for review.
    """

    def propose(self, reading: RawReading) -> MappingProposal: ...

    @property
    def catalog(self) -> "ReviewedCodingAgent":
        """The reviewed rules behind this proposer.

        Approval validation resolves the reviewer's chosen code against this,
        so it must be reachable whether or not a model wrapped the proposer.
        """
        ...


class ReviewedCodingAgent:
    """Deterministic, auditable baseline coding proposer.

    It performs alias similarity, curated code selection, and explicit unit
    conversion using reviewed factors. It is also the grounding source and the
    safety net for the Gemini co-pilot in `coding_llm.py`: the catalog it loads
    is the only vocabulary a model is allowed to choose from, and unit
    arithmetic always runs here, never in the model.
    """

    def __init__(self, rules_path: Path | str, review_threshold: float = 0.9) -> None:
        document = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8"))
        self.system: str = document["system"]
        self.rules: list[dict[str, Any]] = document["rules"]
        self.review_threshold = review_threshold
        self._by_code = {rule["code"]: rule for rule in self.rules}

    # -- catalog access ----------------------------------------------------

    @property
    def catalog(self) -> "ReviewedCodingAgent":
        return self

    def accepted_units_for_rule(self, rule: dict[str, Any]) -> list[str]:
        """Units a *published* quantity may carry for this rule.

        Narrower than `known_units_for_rule`, which also lists the source units
        a conversion accepts as input. A reviewer may say the source was in
        `uS/cm`, but the published quantity has to land on `mS/cm`.
        """
        return list(rule.get("accepted_units", []))

    def rule_for_code(self, code: str) -> dict[str, Any] | None:
        return self._by_code.get(code)

    def coding_for_code(self, code: str) -> Coding | None:
        rule = self._by_code.get(code)
        if not rule:
            return None
        # Display always comes from the reviewed catalog, never from a model.
        return Coding(system=self.system, code=rule["code"], display=rule["display"])

    def catalog_for_prompt(self) -> list[dict[str, Any]]:
        return [
            {
                "code": rule["code"],
                "display": rule["display"],
                "aliases": list(rule.get("aliases", [])),
                "known_units": self.known_units_for_rule(rule),
            }
            for rule in self.rules
        ]

    @staticmethod
    def known_units_for_rule(rule: dict[str, Any]) -> list[str]:
        units = list(rule.get("accepted_units", []))
        units.extend(rule.get("unit_conversions", {}).keys())
        return sorted(dict.fromkeys(units))

    def known_units(self) -> list[str]:
        units: list[str] = []
        for rule in self.rules:
            units.extend(self.known_units_for_rule(rule))
        return sorted(dict.fromkeys(units))

    def codes(self) -> list[str]:
        return [rule["code"] for rule in self.rules]

    # -- matching ----------------------------------------------------------

    def rank(self, parameter: str) -> list[tuple[float, dict[str, Any], str]]:
        """Score every catalog alias against a source parameter label."""
        query = _normalize(parameter)
        ranked: list[tuple[float, dict[str, Any], str]] = []
        for rule in self.rules:
            best_score = 0.0
            best_alias = rule["code"]
            for alias in rule["aliases"]:
                normalized_alias = _normalize(alias)
                score = (
                    1.0
                    if query == normalized_alias
                    else SequenceMatcher(None, query, normalized_alias).ratio()
                )
                if score > best_score:
                    best_score, best_alias = score, alias
            ranked.append((best_score, rule, best_alias))
        return sorted(ranked, key=lambda item: item[0], reverse=True)

    def candidates(self, parameter: str, limit: int = 3) -> list[CandidateCoding]:
        return [
            CandidateCoding(
                code=rule["code"],
                display=rule["display"],
                score=round(score, 2),
                origin="curated-alias",
            )
            for score, rule, _alias in self.rank(parameter)[:limit]
        ]

    def propose(self, reading: RawReading) -> MappingProposal:
        ranked = self.rank(reading.parameter)
        score, rule, alias = ranked[0]

        coding = None
        normalized_value = None
        normalized_unit = None
        rationale = "No sufficiently close curated terminology match."

        if score >= MATCH_FLOOR:
            coding = self.coding_for_code(rule["code"])
            normalized_value, normalized_unit, unit_note = self.normalize_unit(
                reading.value, reading.unit, rule
            )
            if normalized_unit is None:
                score = min(score, UNRESOLVED_UNIT_CEILING)
            rationale = f"Matched input to curated alias '{alias}'. {unit_note}"

        return MappingProposal(
            id=str(uuid4()),
            reading=reading,
            coding=coding,
            normalized_value=normalized_value,
            normalized_unit=normalized_unit,
            confidence=round(min(score, 0.99), 2),
            rationale=rationale,
            requires_review=True,
            proposer=ProposerKind.CURATED,
            candidates=self.candidates(reading.parameter),
        )

    # -- unit handling -----------------------------------------------------

    @staticmethod
    def normalize_unit(
        value: float, unit: str, rule: dict[str, Any]
    ) -> tuple[float | None, str | None, str]:
        """Convert a source quantity using reviewed factors only.

        This is deliberately the *only* place a published number is computed.
        No model output ever performs this arithmetic.

        A converted value outside the rule's reviewed `plausible_range` is
        withheld exactly like an unresolvable unit: no number, no publication,
        no alert, and approval blocked until a person corrects it. Both
        proposers route their arithmetic through here, so a failed sensor
        cannot raise an alert down either path.
        """
        if unit in rule.get("accepted_units", []):
            converted, target, note = value, unit, "Unit is an accepted UCUM code."
        else:
            conversion = rule.get("unit_conversions", {}).get(unit)
            if not conversion:
                return None, None, f"Unit '{unit}' needs reviewer correction."
            converted = value * float(conversion["factor"])
            target = conversion["target"]
            note = f"Converted from {unit}."

        implausible = range_violation(converted, target, rule)
        if implausible:
            return None, None, f"{note} {implausible}"
        return converted, target, note


def range_violation(value: float, unit: str, rule: dict[str, Any]) -> str | None:
    """Describe why a normalized quantity is outside its reviewed bounds, or None."""
    limits = rule.get("plausible_range")
    if not limits:
        return None
    low, high = float(limits["min"]), float(limits["max"])
    if low <= value <= high:
        return None
    return (
        f"Normalized value {value:g} {unit} is outside the reviewed plausible range "
        f"{low:g}-{high:g} {unit}; quantity withheld for reviewer correction."
    )
