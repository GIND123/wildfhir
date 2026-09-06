"""Unstructured-note intake: free text in, reviewable proposals out.

The hardest part of the fragmentation problem is not the API — it is that a lot
of environmental evidence never arrives as a row at all. It arrives as a
voivodeship bulletin, a Wasserwirtschaftsamt email, an angler's message, or a
line in a field logbook.

This module asks Gemini to extract only what is literally written, keeps the
original label and unit untouched, and hands each extraction to the normal
terminology proposer. Both AI stages land in the same place: a *pending*
proposal that a human must approve.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from aquafhir.gemini import GeminiClient, GeminiError, mark_degraded
from aquafhir.models import (
    AiAttribution,
    IntakeRequest,
    RawReading,
    SourceType,
)
from aquafhir.prompts import (
    INTAKE_SYSTEM,
    INTAKE_TEMPLATE_ID,
    intake_prompt,
    intake_schema,
)

logger = logging.getLogger(__name__)

ExtractionOutcome = tuple[list[RawReading], list[str], AiAttribution | None, dict | None]


class UnstructuredIntake:
    def __init__(self, gemini: GeminiClient) -> None:
        self.gemini = gemini

    @property
    def available(self) -> bool:
        return self.gemini.enabled

    def extract(self, request: IntakeRequest) -> ExtractionOutcome:
        result = self.gemini.generate_json(
            template_id=INTAKE_TEMPLATE_ID,
            system=INTAKE_SYSTEM,
            prompt=intake_prompt(
                text=request.text,
                default_site_name=request.default_site_name,
                default_site_code=request.default_site_code,
            ),
            schema=intake_schema([item.value for item in SourceType]),
        )
        payload = result.data
        if not isinstance(payload, dict):
            raise GeminiError(
                "Gemini intake response was not a JSON object",
                category="invalid-response",
                audit=mark_degraded(result.audit, "invalid-response"),
            )

        warnings = [str(item) for item in payload.get("warnings", []) if str(item).strip()]
        readings: list[RawReading] = []
        ingested_at = datetime.now(UTC)

        for index, row in enumerate(payload.get("readings", [])):
            if not isinstance(row, dict):
                warnings.append(f"Extraction {index + 1} was not an object and was discarded.")
                continue
            try:
                readings.append(self._to_reading(row, request, ingested_at, warnings))
            except (KeyError, ValueError, TypeError) as error:
                warnings.append(
                    f"Extraction {index + 1} "
                    f"({row.get('parameter', 'unnamed')!r}) failed validation: {error}"
                )

        attribution = AiAttribution(
            model=result.model,
            template_id=result.template_id,
            prompt_hash=result.prompt_hash,
            response_hash=result.response_hash,
            latency_ms=result.latency_ms,
            evidence=[
                str(row.get("quoted_span", ""))
                for row in payload.get("readings", [])
                if isinstance(row, dict) and row.get("quoted_span")
            ][:5],
        )
        return readings, warnings, attribution, result.audit

    @staticmethod
    def _to_reading(
        row: dict[str, Any],
        request: IntakeRequest,
        ingested_at: datetime,
        warnings: list[str],
    ) -> RawReading:
        observed_raw = row.get("observed_at")
        observed_at = _parse_timestamp(observed_raw)
        if observed_at is None:
            # Never invent an observation time. Record the ingestion time,
            # label it, and let the reviewer correct it.
            observed_at = ingested_at
            warnings.append(
                f"{row.get('parameter', 'reading')!r} carried no usable timestamp; "
                "ingestion time recorded and flagged for reviewer correction."
            )

        source_type = row.get("source_type", request.source_type.value)
        try:
            source_type = SourceType(source_type)
        except ValueError:
            source_type = request.source_type

        return RawReading(
            source_id=request.source_id,
            source_type=source_type,
            parameter=str(row["parameter"]),
            value=float(row["value"]),
            unit=str(row["unit"]),
            observed_at=observed_at,
            site_code=str(row.get("site_code") or request.default_site_code),
            site_name=str(row.get("site_name") or request.default_site_name),
            latitude=_coordinate(row.get("latitude"), request.default_latitude),
            longitude=_coordinate(row.get("longitude"), request.default_longitude),
            raw_payload={
                "extracted_by": "gemini",
                "quoted_span": row.get("quoted_span"),
                "observed_at_in_source": observed_raw,
                "coordinates_in_source": row.get("latitude") is not None,
            },
        )


def _parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _coordinate(value: Any, fallback: float) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
