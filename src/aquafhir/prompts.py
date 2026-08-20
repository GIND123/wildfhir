"""Versioned prompt templates and response schemas for the Gemini co-pilot.

Every template carries an explicit version in its id. The id is hashed into the
provenance chain with the rendered prompt, so changing wording here is a
detectable, reviewable event rather than an invisible behaviour change.

Design rules that apply to all templates:

* The model chooses from a closed, curated vocabulary supplied in the prompt.
  ``responseSchema`` enums enforce that at the API boundary as well.
* The model never performs arithmetic that affects a published quantity. Unit
  conversion stays in ``coding.py`` using the reviewed YAML factors.
* The model never decides whether an alert fires. Thresholds are deterministic.
* Every template is told, in the system instruction, that a human reviews its
  output before anything is published.
"""

from typing import Any

CODING_TEMPLATE_ID = "coding-proposer/v1"
INTAKE_TEMPLATE_ID = "intake-extractor/v1"
BRIEFING_TEMPLATE_ID = "alert-briefing/v1"
SITUATION_TEMPLATE_ID = "situation-report/v1"

NO_MATCH = "NO_MATCH"

_SHARED_GUARDRAILS = (
    "You are a terminology and communication assistant inside a regulated One Health "
    "data pipeline. A qualified human reviewer inspects and approves everything you "
    "produce before any FHIR resource is published or any advisory is sent. "
    "Never claim clinical, veterinary, or regulatory authority. Never invent data. "
    "If the input does not support an answer, say so explicitly rather than guessing."
)


# --------------------------------------------------------------------------
# 1. Terminology coding co-pilot
# --------------------------------------------------------------------------

CODING_SYSTEM = (
    f"{_SHARED_GUARDRAILS}\n\n"
    "Your task is to map one messy environmental measurement label onto exactly one "
    "code from a closed OneAquaHealth (OAH) terminology catalog, and to identify which "
    "known UCUM unit the source unit string actually denotes.\n\n"
    "Hard rules:\n"
    "- Choose a code only from the supplied catalog. If none of them is clearly the same "
    f"physical quantity, answer '{NO_MATCH}'.\n"
    "- Do not convert numbers. The pipeline converts units deterministically from reviewed "
    "factors; you only identify which known unit string the source unit means.\n"
    f"- If the source unit does not match any listed known unit, answer '{NO_MATCH}' for the "
    "unit and explain why in the rationale.\n"
    "- A near-sounding parameter is not a match. Turbidity is not chlorophyll; conductivity "
    "is not salinity concentration; a chlorophyll index is not a chlorophyll concentration.\n"
    "- confidence is your own calibrated probability that a domain expert would accept this "
    "mapping. Be conservative; a human still reviews it.\n"
    "- Keep rationale under 240 characters and write it for a reviewer who must decide "
    "quickly whether to accept."
)


def coding_prompt(
    *,
    parameter: str,
    unit: str,
    value: float,
    source_type: str,
    site_name: str,
    catalog: list[dict[str, Any]],
    rule_candidate: str | None,
) -> str:
    lines = ["CATALOG (the only codes you may choose):"]
    for entry in catalog:
        aliases = ", ".join(entry["aliases"])
        units = ", ".join(entry["known_units"]) or "(none)"
        lines.append(
            f"- code: {entry['code']} | display: {entry['display']}\n"
            f"  known aliases: {aliases}\n"
            f"  known units: {units}"
        )
    lines.append("")
    lines.append("MEASUREMENT TO MAP:")
    lines.append(f"- source parameter label: {parameter!r}")
    lines.append(f"- source unit string: {unit!r}")
    lines.append(f"- numeric value: {value}")
    lines.append(f"- source type: {source_type}")
    lines.append(f"- monitoring site: {site_name}")
    if rule_candidate:
        lines.append("")
        lines.append(
            "The deterministic alias matcher already suggested "
            f"'{rule_candidate}'. Agree only if it is genuinely the same quantity; "
            "disagree clearly if it is wrong."
        )
    return "\n".join(lines)


def coding_schema(code_values: list[str], unit_values: list[str]) -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "code": {
                "type": "STRING",
                "enum": [*code_values, NO_MATCH],
                "description": "Chosen OAH catalog code, or NO_MATCH.",
            },
            "unit_code": {
                "type": "STRING",
                "enum": [*unit_values, NO_MATCH],
                "description": "Which known unit string the source unit denotes, or NO_MATCH.",
            },
            "confidence": {
                "type": "NUMBER",
                "description": "Calibrated probability between 0 and 1.",
            },
            "rationale": {"type": "STRING"},
            "evidence": {
                "type": "ARRAY",
                "description": "Short quoted fragments from the input that justify the choice.",
                "items": {"type": "STRING"},
            },
            "needs_expert_review": {
                "type": "BOOLEAN",
                "description": "True when a domain expert should look especially closely.",
            },
        },
        "required": ["code", "unit_code", "confidence", "rationale", "needs_expert_review"],
        "propertyOrdering": [
            "code",
            "unit_code",
            "confidence",
            "rationale",
            "evidence",
            "needs_expert_review",
        ],
    }


# --------------------------------------------------------------------------
# 2. Unstructured intake extractor
# --------------------------------------------------------------------------

INTAKE_SYSTEM = (
    f"{_SHARED_GUARDRAILS}\n\n"
    "Your task is to extract discrete environmental measurements from an unstructured "
    "note: an agency bulletin, an email, a field logbook line, or a citizen report.\n\n"
    "Hard rules:\n"
    "- Extract only measurements that are literally present. Never interpolate, average, "
    "or infer a value that is not written down.\n"
    "- Keep the parameter label exactly as the source wrote it. Downstream terminology "
    "review maps it; that is not your job.\n"
    "- Keep the unit string exactly as written.\n"
    "- Use ISO 8601 UTC for observed_at. If the note gives no usable timestamp, set it to "
    "null rather than inventing one.\n"
    "- Only fill latitude/longitude when the note states coordinates. Never geocode from "
    "memory.\n"
    "- Put anything ambiguous, contradictory, or discarded into warnings."
)


def intake_prompt(*, text: str, default_site_name: str, default_site_code: str) -> str:
    return (
        "DEFAULTS to use when the note does not name a site:\n"
        f"- site_name: {default_site_name}\n"
        f"- site_code: {default_site_code}\n\n"
        "UNSTRUCTURED NOTE:\n"
        "-----\n"
        f"{text}\n"
        "-----"
    )


def intake_schema(source_types: list[str]) -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "readings": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "parameter": {"type": "STRING"},
                        "value": {"type": "NUMBER"},
                        "unit": {"type": "STRING"},
                        "observed_at": {"type": "STRING", "nullable": True},
                        "site_name": {"type": "STRING"},
                        "site_code": {"type": "STRING"},
                        "latitude": {"type": "NUMBER", "nullable": True},
                        "longitude": {"type": "NUMBER", "nullable": True},
                        "source_type": {"type": "STRING", "enum": source_types},
                        "quoted_span": {
                            "type": "STRING",
                            "description": "The exact source fragment this reading came from.",
                        },
                    },
                    "required": [
                        "parameter",
                        "value",
                        "unit",
                        "site_name",
                        "site_code",
                        "source_type",
                        "quoted_span",
                    ],
                    "propertyOrdering": [
                        "parameter",
                        "value",
                        "unit",
                        "observed_at",
                        "site_name",
                        "site_code",
                        "latitude",
                        "longitude",
                        "source_type",
                        "quoted_span",
                    ],
                },
            },
            "warnings": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["readings", "warnings"],
        "propertyOrdering": ["readings", "warnings"],
    }


# --------------------------------------------------------------------------
# 3. Audience-specific advisory drafting
# --------------------------------------------------------------------------

BRIEFING_SYSTEM = (
    f"{_SHARED_GUARDRAILS}\n\n"
    "Your task is to draft a short internal advisory for one specific professional "
    "audience, based only on facts the deterministic pipeline already established.\n\n"
    "Hard rules:\n"
    "- The threshold decision has already been made by a versioned policy engine. Do not "
    "re-evaluate it, argue with it, or restate its numbers incorrectly.\n"
    "- Use only the supplied observation values, policy metadata, and site history. Do not "
    "add outside facts, case counts, regulatory limits, or historical events.\n"
    "- This is decision support for professionals, not a public warning and not clinical "
    "or veterinary advice. Recommended actions must be investigative or coordinating "
    "steps, never treatment instructions or public messaging that bypasses an authority.\n"
    "- State the limits of the evidence honestly in the uncertainty field, including that "
    "the threshold policy is a demonstration policy when told so.\n"
    "- headline under 90 characters. summary at most 4 sentences. 2-4 recommended actions."
)

AUDIENCE_FRAMING = {
    "public-health": (
        "Public health authority. Cares about human exposure pathways: drinking water "
        "intakes, bathing and recreation, fish consumption, and which populations to warn."
    ),
    "veterinary": (
        "Veterinary and animal health authority. Cares about livestock watering, companion "
        "animal exposure, wildlife and fish mortality, and carcass handling."
    ),
    "water-authority": (
        "Water and environment authority. Cares about the hydrological cause, discharge "
        "sources, sampling density, upstream and downstream propagation, and cross-border "
        "notification duties."
    ),
}


def briefing_prompt(
    *,
    audience: str,
    alert: dict[str, Any],
    policy_id: str,
    policy_status: str,
    observation: dict[str, Any] | None,
    site_history: list[dict[str, Any]],
) -> str:
    framing = AUDIENCE_FRAMING.get(audience, f"Audience: {audience}.")
    history_lines = (
        "\n".join(
            f"- {item['observed_at']}: {item['code']} = {item['value']} {item['unit']}"
            for item in site_history
        )
        or "- (no other approved observations recorded for this site)"
    )
    observed_unit = alert["unit"]
    return (
        f"AUDIENCE: {audience}\n{framing}\n\n"
        "ALERT FACTS (established deterministically; treat as ground truth):\n"
        f"- site: {alert['site_code']}\n"
        f"- indicator code: {alert['rule_code']}\n"
        f"- measured value: {alert['value']} {observed_unit}\n"
        f"- observed at: {alert['observed_at']}\n"
        f"- severity assigned by policy: {alert['severity']}\n"
        f"- policy message: {alert['message']}\n"
        f"- policy id: {policy_id} (status: {policy_status})\n"
        f"- routed audiences: {', '.join(alert['audiences'])}\n"
        f"- FHIR Observation id: {alert['observation_id']}\n\n"
        "OTHER APPROVED OBSERVATIONS AT THIS SITE:\n"
        f"{history_lines}\n\n"
        f"FHIR OBSERVATION PROFILE: "
        f"{(observation or {}).get('meta', {}).get('profile', ['(not supplied)'])[0]}\n"
    )


BRIEFING_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "recommended_actions": {"type": "ARRAY", "items": {"type": "STRING"}},
        "uncertainty": {"type": "STRING"},
        "escalation_question": {
            "type": "STRING",
            "description": "The single question this audience should answer next.",
        },
    },
    "required": [
        "headline",
        "summary",
        "recommended_actions",
        "uncertainty",
        "escalation_question",
    ],
    "propertyOrdering": [
        "headline",
        "summary",
        "recommended_actions",
        "uncertainty",
        "escalation_question",
    ],
}


# --------------------------------------------------------------------------
# 4. Grounded situation report over stored pipeline state
# --------------------------------------------------------------------------

SITUATION_SYSTEM = (
    f"{_SHARED_GUARDRAILS}\n\n"
    "Your task is to summarise the current state of one monitoring pipeline for an "
    "incident coordinator, using only the supplied inventory of approved FHIR "
    "observations and policy alerts.\n\n"
    "Hard rules:\n"
    "- Every statement must be traceable to a supplied row. Cite site codes and indicator "
    "codes explicitly.\n"
    "- Do not predict bloom biology, fish mortality, or human health outcomes. Describe "
    "what the measurements show and what is still unknown.\n"
    "- If the inventory is empty or too thin to support a conclusion, say that plainly.\n"
    "- Name the data gaps that would most change the picture."
)


def situation_prompt(
    *,
    observations: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    pending_count: int,
    policy_id: str,
    policy_status: str,
) -> str:
    observation_lines = (
        "\n".join(
            f"- {item['observed_at']} | {item['site_code']} | {item['code']} = "
            f"{item['value']} {item['unit']} | source: {item['source_type']}"
            for item in observations
        )
        or "- (none)"
    )
    alert_lines = (
        "\n".join(
            f"- {item['observed_at']} | {item['site_code']} | {item['rule_code']} | "
            f"{item['severity']} | audiences: {', '.join(item['audiences'])}"
            for item in alerts
        )
        or "- (none)"
    )
    return (
        f"POLICY IN FORCE: {policy_id} (status: {policy_status})\n"
        f"MAPPINGS STILL AWAITING HUMAN REVIEW: {pending_count}\n\n"
        f"APPROVED AND PUBLISHED OBSERVATIONS:\n{observation_lines}\n\n"
        f"POLICY ALERTS RAISED:\n{alert_lines}\n"
    )


SITUATION_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "situation": {"type": "STRING"},
        "by_site": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "site_code": {"type": "STRING"},
                    "assessment": {"type": "STRING"},
                },
                "required": ["site_code", "assessment"],
                "propertyOrdering": ["site_code", "assessment"],
            },
        },
        "data_gaps": {"type": "ARRAY", "items": {"type": "STRING"}},
        "next_steps": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["headline", "situation", "by_site", "data_gaps", "next_steps"],
    "propertyOrdering": ["headline", "situation", "by_site", "data_gaps", "next_steps"],
}
