"""AI-drafted advisories and grounded situation reports.

A threshold crossing is machine-readable, but the three audiences it routes to
need different things from it. A veterinary officer asks about livestock
watering and carcass handling; a water authority asks about discharge sources
and cross-border notification. Today that translation is a phone call.

Gemini drafts it here — strictly downstream of the deterministic decision. The
policy engine has already decided *whether* to alert, at what severity, and to
whom. The model only writes the prose, only from supplied facts, and the output
is stored as a `draft` that an accountable authority must approve before use.
"""

import logging
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from aquafhir.gemini import GeminiClient, GeminiError
from aquafhir.models import (
    AiAttribution,
    Alert,
    AlertBriefing,
    SiteAssessment,
    SituationReport,
)
from aquafhir.prompts import (
    AUDIENCE_FRAMING,
    BRIEFING_SCHEMA,
    BRIEFING_SYSTEM,
    BRIEFING_TEMPLATE_ID,
    SITUATION_SCHEMA,
    SITUATION_SYSTEM,
    SITUATION_TEMPLATE_ID,
    briefing_prompt,
    situation_prompt,
)

logger = logging.getLogger(__name__)

KNOWN_AUDIENCES = tuple(AUDIENCE_FRAMING)


class BriefingWriter:
    def __init__(self, gemini: GeminiClient) -> None:
        self.gemini = gemini

    @property
    def available(self) -> bool:
        return self.gemini.enabled

    def draft(
        self,
        *,
        alert: Alert,
        audience: str,
        policy_id: str,
        policy_status: str,
        observation: dict[str, Any] | None = None,
        site_history: list[dict[str, Any]] | None = None,
    ) -> AlertBriefing:
        if audience not in alert.audiences:
            raise ValueError(
                f"Audience {audience!r} is not routed for this alert "
                f"({', '.join(alert.audiences)})"
            )

        result = self.gemini.generate_json(
            template_id=BRIEFING_TEMPLATE_ID,
            system=BRIEFING_SYSTEM,
            prompt=briefing_prompt(
                audience=audience,
                alert=alert.model_dump(mode="json"),
                policy_id=policy_id,
                policy_status=policy_status,
                observation=observation,
                site_history=site_history or [],
            ),
            schema=BRIEFING_SCHEMA,
            temperature=0.2,
        )
        payload = result.data
        if not isinstance(payload, dict):
            raise GeminiError("Gemini briefing response was not a JSON object")

        return AlertBriefing(
            id=str(uuid5(NAMESPACE_URL, f"briefing|{alert.id}|{audience}")),
            alert_id=alert.id,
            audience=audience,
            headline=str(payload.get("headline", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            recommended_actions=[
                str(item).strip()
                for item in payload.get("recommended_actions", [])
                if str(item).strip()
            ][:4],
            uncertainty=str(payload.get("uncertainty", "")).strip(),
            escalation_question=str(payload.get("escalation_question", "")).strip(),
            ai=AiAttribution(
                model=result.model,
                template_id=result.template_id,
                prompt_hash=result.prompt_hash,
                response_hash=result.response_hash,
                latency_ms=result.latency_ms,
            ),
        )

    def situation_report(
        self,
        *,
        observations: list[dict[str, Any]],
        alerts: list[dict[str, Any]],
        pending_count: int,
        policy_id: str,
        policy_status: str,
    ) -> SituationReport:
        result = self.gemini.generate_json(
            template_id=SITUATION_TEMPLATE_ID,
            system=SITUATION_SYSTEM,
            prompt=situation_prompt(
                observations=observations,
                alerts=alerts,
                pending_count=pending_count,
                policy_id=policy_id,
                policy_status=policy_status,
            ),
            schema=SITUATION_SCHEMA,
            temperature=0.2,
        )
        payload = result.data
        if not isinstance(payload, dict):
            raise GeminiError("Gemini situation response was not a JSON object")

        return SituationReport(
            headline=str(payload.get("headline", "")).strip(),
            situation=str(payload.get("situation", "")).strip(),
            by_site=[
                SiteAssessment(
                    site_code=str(item.get("site_code", "unknown")),
                    assessment=str(item.get("assessment", "")).strip(),
                )
                for item in payload.get("by_site", [])
                if isinstance(item, dict)
            ],
            data_gaps=[str(item).strip() for item in payload.get("data_gaps", []) if str(item)],
            next_steps=[str(item).strip() for item in payload.get("next_steps", []) if str(item)],
            observations_considered=len(observations),
            alerts_considered=len(alerts),
            pending_reviews=pending_count,
            ai=AiAttribution(
                model=result.model,
                template_id=result.template_id,
                prompt_hash=result.prompt_hash,
                response_hash=result.response_hash,
                latency_ms=result.latency_ms,
            ),
        )
