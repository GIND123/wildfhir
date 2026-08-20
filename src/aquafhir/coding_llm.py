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
from aquafhir.gemini import GeminiClient, GeminiError
from aquafhir.models import (
    AiAttribution,
    CandidateCoding,
    MappingProposal,
    ProposerKind,
    RawReading,
)
from aquafhir.prompts import (
    CODING_SYSTEM,
    CODING_TEMPLATE_ID,
    NO_MATCH,
    coding_prompt,
    coding_schema,
)

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
            or proposal.normalized_unit is None
            or proposal.confidence < self.assist_below_confidence
        )

    # -- proposing ---------------------------------------------------------

    def propose(self, reading: RawReading) -> MappingProposal:
        proposal = self.base.propose(reading)
        if not self.should_consult(proposal):
            return proposal
        try:
            return self._apply_gemini(reading, proposal)
        except GeminiError as error:
            logger.warning("Gemini coding assist unavailable: %s", error)
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
            ),
            schema=coding_schema(codes, units),
        )
        payload = result.data
        if not isinstance(payload, dict):
            raise GeminiError("Gemini coding response was not a JSON object")

        chosen_code = str(payload.get("code", NO_MATCH))
        chosen_unit = str(payload.get("unit_code", NO_MATCH))
        model_confidence = _clamp_confidence(payload.get("confidence"))
        model_rationale = str(payload.get("rationale", "")).strip()
        evidence = [str(item) for item in payload.get("evidence", []) if str(item).strip()]
        needs_expert = bool(payload.get("needs_expert_review", False))

        # Guardrail: the model can only ever name a code that exists in the
        # reviewed catalog. The schema enum makes this unlikely; we re-check
        # because a schema is a request, not a proof.
        rule = self.base.rule_for_code(chosen_code) if chosen_code != NO_MATCH else None
        if chosen_code != NO_MATCH and rule is None:
            raise GeminiError(f"Gemini proposed out-of-catalog code {chosen_code!r}")

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

        if rule is None:
            return self._no_match_proposal(proposal, model_rationale, attribution)

        return self._matched_proposal(
            proposal=proposal,
            reading=reading,
            rule=rule,
            chosen_unit=chosen_unit,
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
        model_confidence: float,
        model_rationale: str,
        attribution: AiAttribution,
        disagreed: bool,
        needs_expert: bool,
    ) -> MappingProposal:
        # The model may only *name* which known unit the source string means, and
        # only when the source string does not already resolve on its own. A unit
        # the reviewed catalog already understands is never reinterpreted, because
        # a plausible-sounding misreading would silently rescale a published value.
        source_unit = reading.unit
        known_units = self.base.known_units_for_rule(rule)
        source_unit_resolves = source_unit in known_units
        unit_note = ""
        if chosen_unit != NO_MATCH and chosen_unit != source_unit:
            if source_unit_resolves:
                unit_note = (
                    f"AI read the unit as '{chosen_unit}', but source unit "
                    f"'{source_unit}' already resolves; source unit kept. "
                )
            elif chosen_unit in known_units:
                unit_note = f"AI read source unit '{source_unit}' as UCUM '{chosen_unit}'. "
                source_unit = chosen_unit
            else:
                unit_note = (
                    f"AI suggested unit '{chosen_unit}', which is not valid for "
                    f"{rule['code']}; ignored. "
                )

        value, unit, conversion_note = self.base.normalize_unit(reading.value, source_unit, rule)

        confidence = min(model_confidence, self.confidence_ceiling)
        if unit is None:
            confidence = min(confidence, UNRESOLVED_UNIT_CEILING)
        if disagreed or needs_expert:
            # Never let a contested mapping look settled to a reviewer.
            confidence = min(confidence, 0.80)

        proposal.coding = self.base.coding_for_code(rule["code"])
        proposal.normalized_value = value
        proposal.normalized_unit = unit
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
