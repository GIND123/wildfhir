"""Gemini-assisted terminology coding, wrapped in deterministic guardrails.

The co-pilot exists because real environmental feeds do not say
``electrical conductivity``. They say ``EC_uScm``, ``Leitfähigkeit``,
``przewodnosc``, ``cond. (25C)``. String similarity fails on all of those; a
language model does not. But a language model must never be trusted with the
parts that decide what gets published.

The split enforced here:

+---------------------------+------------------------------------------------+
| Gemini may decide         | Deterministic code decides                      |
+---------------------------+------------------------------------------------+
| which catalog code a      | the code's display text (read from the YAML)    |
| messy label denotes       | the unit conversion factor and resulting number |
| which known unit string   | whether the proposal needs review (always yes)  |
| the source unit denotes   | whether an alert fires                          |
+---------------------------+------------------------------------------------+

If Gemini is unreachable, misconfigured, off, or returns something outside the
catalog, this class silently degrades to the curated proposal. The pipeline
never fails because of the AI layer.
"""

import logging
from typing import Any

from aquafhir.coding import UNRESOLVED_UNIT_CEILING, ReviewedCodingAgent
from aquafhir.config import AssistMode
from aquafhir.gemini import GeminiClient, GeminiError, mark_degraded
from aquafhir.models import (
    AiAttribution,
    CandidateCoding,
    MappingProposal,
    ProposerKind,
    RawReading,
    UnitSuggestionResult,
)
from aquafhir.prompts import (
    CODING_SYSTEM,
    CODING_TEMPLATE_ID,
    NO_MATCH,
    coding_prompt,
    coding_schema,
)
from aquafhir.unit_assist import make_suggestion

logger = logging.getLogger(__name__)


class GeminiCodingAgent:
    """A `CodingProposer` that consults Gemini, then re-checks it against rules."""

    def __init__(
        self,
        base: ReviewedCodingAgent,
        gemini: GeminiClient,
        *,
        assist_mode: AssistMode = AssistMode.AUTO,
        assist_below_confidence: float = 0.95,
        confidence_ceiling: float = 0.95,
    ) -> None:
        self.base = base
        self.gemini = gemini
        self.assist_mode = assist_mode
        self.assist_below_confidence = assist_below_confidence
        self.confidence_ceiling = confidence_ceiling

    # -- policy ------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.gemini.enabled and self.assist_mode is not AssistMode.OFF

    def should_consult(self, proposal: MappingProposal) -> bool:
        if not self.available:
            return False
        if self.assist_mode is AssistMode.ALWAYS:
            return True
        # `auto`: spend a call only where the deterministic matcher is weak or
        # could not resolve the unit — which is exactly where it gets things
        # wrong on real-world feeds.
        return (
            proposal.coding is None
            or not proposal.has_publishable_value
            or proposal.confidence < self.assist_below_confidence
        )

    # -- proposing ---------------------------------------------------------

    @property
    def catalog(self) -> ReviewedCodingAgent:
        """The curated rules the model is grounded in, and the review gate checks."""
        return self.base

    def propose(self, reading: RawReading) -> MappingProposal:
        proposal = self.base.propose(reading)
        if not self.should_consult(proposal):
            return proposal
        try:
            return self._apply_gemini(reading, proposal)
        except GeminiError as error:
            logger.warning("Gemini coding assist unavailable: %s", error)
            # Carried on the proposal so the failure is attributable to *this*
            # reading, and so the console can distinguish a rules-only result
            # from one where the model was tried and refused.
            proposal.ai_audit = error.audit
            proposal.rationale = (
                f"{proposal.rationale} AI assist unavailable ({type(error).__name__}); "
                "curated result shown."
            )
            return proposal

    def _apply_gemini(self, reading: RawReading, proposal: MappingProposal) -> MappingProposal:
        catalog = self.base.catalog_for_prompt()
        codes = self.base.codes()
        units = self.base.known_units()
        rule_candidate = proposal.coding.code if proposal.coding else None

        result = self.gemini.generate_json(
            template_id=CODING_TEMPLATE_ID,
            system=CODING_SYSTEM,
            prompt=coding_prompt(
                parameter=reading.parameter,
                unit=reading.unit,
                value=reading.value,
                source_type=reading.source_type.value,
                site_name=reading.site_name,
                catalog=catalog,
                rule_candidate=rule_candidate,
                coded_value=reading.coded_value,
            ),
            schema=coding_schema(codes, units, self.base.known_values()),
        )
        payload = result.data
        if not isinstance(payload, dict):
            raise GeminiError(
                "Gemini coding response was not a JSON object",
                category="invalid-response",
                audit=mark_degraded(result.audit, "invalid-response"),
            )

        chosen_code = str(payload.get("code", NO_MATCH))
        chosen_unit = str(payload.get("unit_code", NO_MATCH))
        chosen_value = str(payload.get("value_code", NO_MATCH) or NO_MATCH)
        model_confidence = _clamp_confidence(payload.get("confidence"))
        model_rationale = str(payload.get("rationale", "")).strip()
        evidence = [str(item) for item in payload.get("evidence", []) if str(item).strip()]
        needs_expert = bool(payload.get("needs_expert_review", False))

        # Guardrail: the model can only ever name a code that exists in the
        # reviewed catalog. The schema enum makes this unlikely; we re-check
        # because a schema is a request, not a proof.
        rule = self.base.rule_for_code(chosen_code) if chosen_code != NO_MATCH else None
        if chosen_code != NO_MATCH and rule is None:
            raise GeminiError(
                f"Gemini proposed out-of-catalog code {chosen_code!r}",
                category="out-of-catalog",
                audit=mark_degraded(result.audit, "out-of-catalog"),
            )

        disagreed = bool(rule_candidate and chosen_code != rule_candidate)
        attribution = AiAttribution(
            model=result.model,
            template_id=result.template_id,
            prompt_hash=result.prompt_hash,
            response_hash=result.response_hash,
            latency_ms=result.latency_ms,
            grounded_codes=codes,
            evidence=evidence[:5],
            model_confidence=model_confidence,
            disagreed_with_rules=disagreed,
            needs_expert_review=needs_expert,
        )

        proposal.ai_audit = result.audit
        if rule is None:
            return self._no_match_proposal(proposal, model_rationale, attribution)

        return self._matched_proposal(
            proposal=proposal,
            reading=reading,
            rule=rule,
            chosen_unit=chosen_unit,
            chosen_value=chosen_value,
            model_confidence=model_confidence,
            model_rationale=model_rationale,
            attribution=attribution,
            disagreed=disagreed,
            needs_expert=needs_expert,
        )

    def _no_match_proposal(
        self,
        proposal: MappingProposal,
        model_rationale: str,
        attribution: AiAttribution,
    ) -> MappingProposal:
        """The model declined to map. Withhold the code and force a decision."""
        proposal.coding = None
        proposal.normalized_value = None
        proposal.normalized_unit = None
        proposal.normalized_coding = None
        proposal.confidence = 0.0
        proposal.proposer = ProposerKind.GEMINI_ASSISTED
        proposal.ai = attribution
        proposal.rationale = (
            "AI co-pilot found no safe match in the curated OAH catalog. "
            f"{model_rationale} A reviewer must supply a code or reject."
        ).strip()
        return proposal

    def _matched_proposal(
        self,
        *,
        proposal: MappingProposal,
        reading: RawReading,
        rule: dict[str, Any],
        chosen_unit: str,
        chosen_value: str,
        model_confidence: float,
        model_rationale: str,
        attribution: AiAttribution,
        disagreed: bool,
        needs_expert: bool,
    ) -> MappingProposal:
        unit_note = ""
        value: float | None = None
        unit: str | None = None
        value_coding = None
        if reading.is_coded:
            # Same rule as for units: the model may *name* which reviewed
            # value-set concept the source's word means, and only when the word
            # does not already resolve on its own. `normalize_coded` still
            # decides whether that name is in the set.
            source_word = reading.coded_value or ""
            resolved, _note = self.base.normalize_coded(source_word, rule)
            if resolved is None and chosen_value != NO_MATCH:
                candidate, _ = self.base.normalize_coded(chosen_value, rule)
                if candidate is not None:
                    unit_note = f"AI read coded value '{source_word}' as '{chosen_value}'. "
                    source_word = chosen_value
                else:
                    unit_note = (
                        f"AI suggested value '{chosen_value}', which is not in the value set "
                        f"for {rule['code']}; ignored. "
                    )
            value_coding, conversion_note = self.base.normalize_coded(source_word, rule)
            resolved_any = value_coding is not None
        else:
            # The model may only *name* which known unit the source string means,
            # and only when the source string does not already resolve on its own.
            # A unit the reviewed catalog already understands is never
            # reinterpreted, because a plausible-sounding misreading would
            # silently rescale a published value.
            source_unit = self.base.canonical_unit(reading.unit, rule)
            known_units = self.base.known_units_for_rule(rule)
            source_unit_resolves = source_unit in known_units
            interpreted_by_ai = False
            if chosen_unit != NO_MATCH and chosen_unit != source_unit:
                if source_unit_resolves:
                    unit_note = (
                        f"AI read the unit as '{chosen_unit}', but source unit "
                        f"'{source_unit}' already resolves; source unit kept. "
                    )
                elif chosen_unit in known_units:
                    unit_note = f"AI read source unit '{source_unit}' as UCUM '{chosen_unit}'. "
                    source_unit = chosen_unit
                    interpreted_by_ai = True
                else:
                    unit_note = (
                        f"AI suggested unit '{chosen_unit}', which is not valid for "
                        f"{rule['code']}; ignored. "
                    )
            value, unit, conversion_note = self.base.normalize_unit(
                reading.value if reading.value is not None else 0.0, source_unit, rule
            )
            resolved_any = unit is not None

            if interpreted_by_ai and value is not None and unit is not None:
                conversion = rule.get("unit_conversions", {}).get(source_unit)
                try:
                    suggestion = make_suggestion(
                        reading, rule, interpreted_unit=source_unit, target=unit,
                        factor=float(conversion["factor"]) if conversion else 1.0, offset=0.0,
                        rationale=model_rationale or unit_note, ai=attribution,
                        origin="ai-interpretation",
                    )
                except ValueError as error:
                    raise GeminiError(
                        "Gemini returned an unusable unit interpretation",
                        category="invalid-response",
                        audit=mark_degraded(proposal.ai_audit or {}, "invalid-response"),
                    ) from error
                proposal.unit_suggestions[rule["code"]] = UnitSuggestionResult(
                    status="suggested", suggestion=suggestion,
                    message="AI unit interpretation, uncited. Explicit expert review required.",
                )
                value, unit = None, None
                conversion_note += " AI unit interpretation requires an expert correction."

        confidence = min(model_confidence, self.confidence_ceiling)
        if not resolved_any:
            confidence = min(confidence, UNRESOLVED_UNIT_CEILING)
        if disagreed or needs_expert:
            # Never let a contested mapping look settled to a reviewer.
            confidence = min(confidence, 0.80)

        proposal.coding = self.base.coding_for_code(rule["code"])
        proposal.leg = self.base.leg_for_rule(rule)
        proposal.normalized_value = value
        proposal.normalized_unit = unit
        proposal.normalized_coding = value_coding
        proposal.confidence = round(confidence, 2)
        proposal.proposer = ProposerKind.GEMINI_ASSISTED
        proposal.ai = attribution
        proposal.rationale = " ".join(
            part
            for part in (
                model_rationale,
                unit_note.strip(),
                conversion_note,
                "AI co-pilot disagrees with the curated alias match — check carefully."
                if disagreed
                else "",
            )
            if part
        )
        proposal.candidates = _merge_candidates(proposal.candidates, rule, model_confidence)
        return proposal


def _clamp_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _merge_candidates(
    existing: list[CandidateCoding], rule: dict[str, Any], score: float
) -> list[CandidateCoding]:
    ai_pick = CandidateCoding(
        code=rule["code"],
        display=rule["display"],
        score=round(score, 2),
        origin="gemini",
    )
    others = [item for item in existing if item.code != rule["code"]]
    return [ai_pick, *others][:4]
