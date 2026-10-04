import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import yaml

from aquafhir.models import (
    AcceptedValue,
    CandidateCoding,
    Coding,
    MappingProposal,
    OneHealthLeg,
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

    A rule may describe a *quantity* indicator (`accepted_units`, optional
    `unit_conversions` and `plausible_range`), a *coded* indicator
    (`value_set`), or both. Coded indicators are how the OAH IG models foam,
    macrophytes and the ordinal citizen-science assessments: the published
    value is a concept from a reviewed value set, never a number.
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

    @staticmethod
    def accepted_values_for_rule(rule: dict[str, Any]) -> list[AcceptedValue]:
        """Concepts a *published* coded value may be, from the IG's value set."""
        return [
            AcceptedValue(
                code=item["code"],
                display=item["display"],
                aliases=list(item.get("aliases", [])),
            )
            for item in (rule.get("value_set") or {}).get("codes", [])
        ]

    @staticmethod
    def leg_for_rule(rule: dict[str, Any]) -> OneHealthLeg:
        return OneHealthLeg(rule.get("leg", OneHealthLeg.ENVIRONMENTAL.value))

    @staticmethod
    def takes_quantity(rule: dict[str, Any]) -> bool:
        return bool(rule.get("accepted_units"))

    @staticmethod
    def takes_coded_value(rule: dict[str, Any]) -> bool:
        return bool((rule.get("value_set") or {}).get("codes"))

    def rule_for_code(self, code: str) -> dict[str, Any] | None:
        return self._by_code.get(code)

    def coding_for_code(self, code: str) -> Coding | None:
        rule = self._by_code.get(code)
        if not rule:
            return None
        # Display always comes from the reviewed catalog, never from a model.
        return Coding(system=self.system, code=rule["code"], display=rule["display"])

    def value_coding_for(self, rule: dict[str, Any], code: str) -> Coding | None:
        """The canonical Coding for one value-set concept, or None."""
        for item in self.accepted_values_for_rule(rule):
            if item.code == code:
                system = (rule.get("value_set") or {}).get("system") or self.system
                return Coding(system=system, code=item.code, display=item.display)
        return None

    def catalog_for_prompt(self) -> list[dict[str, Any]]:
        return [
            {
                "code": rule["code"],
                "display": rule["display"],
                "aliases": list(rule.get("aliases", [])),
                "known_units": self.known_units_for_rule(rule),
                "known_values": [item.code for item in self.accepted_values_for_rule(rule)],
                "leg": self.leg_for_rule(rule).value,
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

    def known_values(self) -> list[str]:
        values: list[str] = []
        for rule in self.rules:
            values.extend(item.code for item in self.accepted_values_for_rule(rule))
        return sorted(dict.fromkeys(values))

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

    def unit_candidates(self, reading: RawReading, limit: int = 1) -> list[CandidateCoding]:
        """Suggest a code when exactly one reviewed rule recognizes the unit."""
        matches = [
            rule for rule in self.rules
            if self.canonical_unit(reading.unit, rule) in self.known_units_for_rule(rule)
        ]
        if len(matches) != 1:
            return []
        rule = matches[0]
        return [CandidateCoding(
            code=rule["code"], display=rule["display"], score=0.86, origin="reviewed-unit"
        )][:limit]

    def propose(self, reading: RawReading) -> MappingProposal:
        ranked = self.rank(reading.parameter)
        score, rule, alias = ranked[0]
        unit_candidates = self.unit_candidates(reading)

        coding = None
        normalized_value = None
        normalized_unit = None
        normalized_coding = None
        leg = OneHealthLeg.ENVIRONMENTAL
        rationale = "No sufficiently close curated terminology match."

        if score >= MATCH_FLOOR:
            coding = self.coding_for_code(rule["code"])
            leg = self.leg_for_rule(rule)
            if reading.is_coded:
                normalized_coding, note = self.normalize_coded(reading.coded_value or "", rule)
                if normalized_coding is None:
                    score = min(score, UNRESOLVED_UNIT_CEILING)
            else:
                normalized_value, normalized_unit, note = self.normalize_unit(
                    reading.value if reading.value is not None else 0.0, reading.unit, rule
                )
                if normalized_unit is None:
                    score = min(score, UNRESOLVED_UNIT_CEILING)
            rationale = f"Matched input to curated alias '{alias}'. {note}"
        elif unit_candidates:
            rationale = (
                f"{rationale} Source unit '{reading.unit}' uniquely suggests "
                f"{unit_candidates[0].display}; reviewer must confirm the code."
            )

        return MappingProposal(
            id=str(uuid4()),
            reading=reading,
            coding=coding,
            normalized_value=normalized_value,
            normalized_unit=normalized_unit,
            normalized_coding=normalized_coding,
            leg=leg,
            confidence=round(min(score, 0.99), 2),
            rationale=rationale,
            requires_review=True,
            proposer=ProposerKind.CURATED,
        candidates=(unit_candidates + [
            candidate for candidate in self.candidates(reading.parameter)
            if candidate.code not in {item.code for item in unit_candidates}
        ])[:3],
        )

    # -- unit handling -----------------------------------------------------

    @staticmethod
    def canonical_unit(unit: str, rule: dict[str, Any]) -> str:
        """Resolve explicit spelling aliases without folding case-sensitive SI prefixes.

        Only spellings with exactly one physical meaning are folded: whitespace,
        the micro sign versus the letter u, lower-case litre (UCUM lists `l` and
        `L` as the same unit), lower-case CFU, the French `UFC` (unités formant
        colonie, the same colony count), and word spellings of Celsius.
        `MG/L` stays unresolved on purpose: in UCUM `M` is mega, and guessing
        that a shouting export meant milligrams is exactly the kind of silent
        scale change this bridge exists to refuse.
        """
        known = ReviewedCodingAgent.known_units_for_rule(rule)
        compact = re.sub(r"\s+", "", unit).replace("\u00b5", "u").replace("\u03bc", "u")
        aliases = {
            "us/cm": "uS/cm",
            "\u00b0C": "Cel",
            "Celsius": "Cel",
            "celsius": "Cel",
            "degC": "Cel",
            "pH": "[pH]",
            "pHunit": "[pH]",
            "pHunits": "[pH]",
            "unit\u00e9pH": "unit\u00e9 pH",
            "unitepH": "unit\u00e9 pH",
            "ppb": "[ppb]",
            "per100000": "{cases}/100000",
            "per100,000": "{cases}/100000",
            "/100000": "{cases}/100000",
            "/100,000": "{cases}/100000",
            "cases/100000": "{cases}/100000",
            "cases/100,000": "{cases}/100000",
        }
        # Word spellings of a unit are case-insensitive; symbols are not.
        word_aliases = {
            "celsius": "Cel",
            "degc": "Cel",
            "degreescelsius": "Cel",
            "degreecelsius": "Cel",
            "\u00b0c": "Cel",
            "us/cm": "uS/cm",
            # A band-ratio index is dimensionless; UCUM writes that as `1`.
            # Only folded for a rule whose accepted unit is `1` (see `known`).
            "index": "1",
            "dimensionless": "1",
            "unitless": "1",
        }
        candidates = [aliases.get(compact, compact)]
        lowered = word_aliases.get(compact.casefold())
        if lowered:
            candidates.append(lowered)
        # UCUM: `l` and `L` are both the litre, so a lower-case denominator is a
        # spelling, not a scale. The prefix in front of it is left untouched.
        litre_fixed = re.sub(r"(/(?:100)?[mdc]?)l$", lambda m: m.group(1) + "L", compact)
        litre_fixed = re.sub(r"^cfu(?=/)", "CFU", litre_fixed)
        litre_fixed = re.sub(r"^ufc(?=/)", "CFU", litre_fixed, flags=re.IGNORECASE)
        litre_fixed = re.sub(r"^\{cfu\}", "{cfu}", litre_fixed)
        if litre_fixed != compact:
            candidates.append(aliases.get(litre_fixed, litre_fixed))
        for candidate in candidates:
            if candidate in known:
                return candidate
        return unit

    @classmethod
    def normalize_unit(
        cls, value: float, unit: str, rule: dict[str, Any]
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
        if not cls.takes_quantity(rule):
            return (
                None,
                None,
                f"'{rule['code']}' publishes a coded value from a reviewed value set, "
                "not a quantity; a number cannot be published for it.",
            )
        original_unit = unit
        unit = cls.canonical_unit(unit, rule)
        if unit in rule.get("accepted_units", []):
            converted, target, note = value, unit, "Unit is an accepted UCUM code."
        else:
            conversion = rule.get("unit_conversions", {}).get(unit)
            if not conversion:
                return None, None, f"Unit '{unit}' needs reviewer correction."
            converted = value * float(conversion["factor"])
            target = conversion["target"]
            note = f"Converted from {unit}."
        # A source that wrote -0.0 (or a factor that underflowed to it) must
        # not publish a signed zero: FHIR readers treat "-0.0" as a value.
        if converted == 0:
            converted = 0.0

        if unit != original_unit:
            note = f"Recognized '{original_unit}' as '{unit}' using a reviewed alias. {note}"
        implausible = range_violation(converted, target, rule)
        if implausible:
            return None, None, f"{note} {implausible}"
        return converted, target, note

    def normalize_coded(
        self, coded_value: str, rule: dict[str, Any]
    ) -> tuple[Coding | None, str]:
        """Resolve a source's word onto one concept of the rule's value set.

        Exact and alias matches only, after case and punctuation folding. There
        is deliberately no fuzzy matching here: "some foam" is not "extensive",
        and the cost of a wrong coded value is a wrong published fact. The
        co-pilot may *name* which concept a phrase means; this method still
        decides whether that name is in the reviewed set.
        """
        if not self.takes_coded_value(rule):
            return (
                None,
                f"'{rule['code']}' publishes a quantity; a coded value cannot be published "
                "for it. Supply a numeric value with a unit instead.",
            )
        wanted = _normalize(coded_value)
        for item in self.accepted_values_for_rule(rule):
            names = [item.code, item.display, *item.aliases]
            if any(_normalize(name) == wanted for name in names):
                coding = self.value_coding_for(rule, item.code)
                return (
                    coding,
                    f"Coded value '{coded_value}' is '{item.code}' in the reviewed value set.",
                )
        allowed = ", ".join(item.code for item in self.accepted_values_for_rule(rule))
        return (
            None,
            f"Coded value '{coded_value}' is not in the reviewed value set ({allowed}); "
            "needs reviewer correction.",
        )


def range_violation(value: float, unit: str, rule: dict[str, Any]) -> str | None:
    """Describe why a normalized quantity is outside its reviewed bounds, or None.

    A count (`{count}`, `{cfu}/dL`, `{cases}/100000` share the annotation
    form) is also held to being a whole number when its unit is a bare count:
    12.5 dead fish is not a measurement any source can have made.
    """
    if value != value or value in (float("inf"), float("-inf")):
        return (
            f"Normalized value {value!r} {unit} is not a finite number; "
            "quantity withheld for reviewer correction."
        )
    if unit == "{count}" and value != int(value):
        return (
            f"Normalized value {value:g} {unit} is not a whole number; a count cannot "
            "be fractional, so the quantity is withheld for reviewer correction."
        )
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
