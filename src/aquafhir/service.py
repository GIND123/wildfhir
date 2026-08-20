import csv
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aquafhir.briefing import KNOWN_AUDIENCES, BriefingWriter
from aquafhir.coding import CodingProposer
from aquafhir.fhir import (
    OAH_LOCATION_PROFILE,
    OAH_OBSERVATION_PROFILE,
    FhirClient,
    build_resources,
    transaction_bundle,
)
from aquafhir.gemini import GeminiError
from aquafhir.intake import UnstructuredIntake
from aquafhir.models import (
    Alert,
    AlertBriefing,
    ApprovalResult,
    BatchApprovalResult,
    BatchReviewDecision,
    IntakeRequest,
    IntakeResult,
    MappingProposal,
    RawReading,
    RejectDecision,
    ReviewDecision,
    ReviewStatus,
    SituationReport,
)
from aquafhir.repository import Repository
from aquafhir.thresholds import ThresholdPolicy

logger = logging.getLogger(__name__)


class ProposalNotFoundError(LookupError):
    pass


class AlertNotFoundError(LookupError):
    pass


class InvalidReviewStateError(ValueError):
    pass


class AiUnavailableError(RuntimeError):
    """Raised when an AI-only endpoint is called without a working Gemini key."""


class BridgeService:
    def __init__(
        self,
        repository: Repository,
        coding_agent: CodingProposer,
        thresholds: ThresholdPolicy,
        fhir_client: FhirClient,
        intake: UnstructuredIntake | None = None,
        briefing_writer: BriefingWriter | None = None,
        replay_path: Path | None = None,
    ) -> None:
        self.repository = repository
        self.coding_agent = coding_agent
        self.thresholds = thresholds
        self.fhir_client = fhir_client
        self.intake = intake
        self.briefing_writer = briefing_writer
        self.replay_path = replay_path

    # -- ingestion ---------------------------------------------------------

    def propose(self, reading: RawReading) -> MappingProposal:
        proposal = self.coding_agent.propose(reading)
        self.repository.save_proposal(proposal)
        self.repository.append_provenance(
            "mapping-proposed", proposal.id, proposal.model_dump(mode="json")
        )
        return proposal

    def replay(self, path: Path | None = None) -> list[MappingProposal]:
        """Load the transparent synthetic Oder timeline as pending proposals."""
        source = path or self.replay_path
        if source is None or not source.exists():
            raise FileNotFoundError(f"Replay dataset not found: {source}")
        proposals: list[MappingProposal] = []
        with source.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                proposals.append(self.propose(_reading_from_csv_row(row)))
        return proposals

    def ingest_unstructured(self, request: IntakeRequest) -> IntakeResult:
        if self.intake is None or not self.intake.available:
            raise AiUnavailableError(
                "Unstructured intake needs GEMINI_API_KEY; use POST /api/v1/proposals instead"
            )
        readings, warnings, attribution = self.intake.extract(request)
        proposals = [self.propose(reading) for reading in readings]
        self.repository.append_provenance(
            "unstructured-intake",
            attribution.prompt_hash if attribution else "no-attribution",
            {
                "source_id": request.source_id,
                "characters": len(request.text),
                "extracted": len(readings),
                "warnings": warnings,
                "proposal_ids": [item.id for item in proposals],
                "ai": attribution.model_dump(mode="json") if attribution else None,
            },
        )
        return IntakeResult(
            proposals=proposals,
            warnings=warnings,
            extracted_count=len(readings),
            rejected_count=max(0, len(warnings) - len(readings)),
            ai=attribution,
        )

    # -- review ------------------------------------------------------------

    def approve(self, proposal_id: str, decision: ReviewDecision) -> ApprovalResult:
        proposal = self._pending_proposal(proposal_id)
        if decision.coding:
            proposal.coding = decision.coding
        if decision.normalized_value is not None and decision.normalized_unit:
            proposal.normalized_value = decision.normalized_value
            proposal.normalized_unit = decision.normalized_unit
        if not proposal.coding or proposal.normalized_value is None or not proposal.normalized_unit:
            raise InvalidReviewStateError(
                "Proposal needs a coding, normalized value, and normalized UCUM unit"
            )

        location, organization, observation = build_resources(proposal)
        validation = {
            "location": self.fhir_client.validate(location, OAH_LOCATION_PROFILE),
            "observation": self.fhir_client.validate(observation, OAH_OBSERVATION_PROFILE),
        }
        publication = self.fhir_client.publish(
            transaction_bundle((location, organization, observation))
        )
        fhir_response = {"validation": validation, "transaction": publication}

        proposal.status = ReviewStatus.APPROVED
        proposal.reviewer = decision.reviewer
        proposal.reviewed_at = datetime.now(UTC)
        self.repository.save_proposal(proposal)
        self.repository.save_observation(proposal.id, observation)
        self.repository.append_provenance(
            "mapping-approved",
            proposal.id,
            {
                "reviewer": decision.reviewer,
                "observation_id": observation["id"],
                "proposer": proposal.proposer.value,
                "ai_accepted": proposal.ai is not None,
                "ai_prompt_hash": proposal.ai.prompt_hash if proposal.ai else None,
                "reviewer_overrode_coding": decision.coding is not None,
                "reviewer_overrode_quantity": decision.normalized_value is not None,
            },
        )
        alerts = self._evaluate_and_store(observation)
        return ApprovalResult(
            proposal=proposal,
            observation=observation,
            fhir_response=fhir_response,
            alerts=alerts,
        )

    def approve_batch(self, decision: BatchReviewDecision) -> BatchApprovalResult:
        result = BatchApprovalResult()
        for proposal_id in decision.proposal_ids:
            try:
                result.approved.append(
                    self.approve(proposal_id, ReviewDecision(reviewer=decision.reviewer))
                )
            except (ProposalNotFoundError, InvalidReviewStateError, ValueError) as error:
                result.failures.append({"proposal_id": proposal_id, "detail": str(error)})
        return result

    def reject(self, proposal_id: str, decision: RejectDecision) -> MappingProposal:
        proposal = self._pending_proposal(proposal_id)
        proposal.status = ReviewStatus.REJECTED
        proposal.reviewer = decision.reviewer
        proposal.reviewed_at = datetime.now(UTC)
        self.repository.save_proposal(proposal)
        self.repository.append_provenance(
            "mapping-rejected",
            proposal.id,
            {
                "reviewer": decision.reviewer,
                "reason": decision.reason,
                "proposer": proposal.proposer.value,
                "ai_prompt_hash": proposal.ai.prompt_hash if proposal.ai else None,
            },
        )
        return proposal

    # -- alerting ----------------------------------------------------------

    def process_webhook_observation(self, resource: dict[str, Any]) -> list[Alert]:
        if resource.get("resourceType") != "Observation":
            return []
        return self._evaluate_and_store(resource)

    def process_subscription_notification(self) -> tuple[int, list[Alert]]:
        started_at = datetime.now(UTC)
        cursor = self.repository.get_cursor("fhir-last-sync")
        since = datetime.fromisoformat(cursor) if cursor else started_at - timedelta(minutes=5)
        observations = self.fhir_client.fetch_recent_observations(since)
        alerts = [
            alert
            for observation in observations
            for alert in self._evaluate_and_store(observation)
        ]
        self.repository.set_cursor("fhir-last-sync", started_at.isoformat())
        return len(observations), alerts

    # -- AI advisory surfaces ---------------------------------------------

    def draft_briefing(self, alert_id: str, audience: str) -> AlertBriefing:
        if self.briefing_writer is None or not self.briefing_writer.available:
            raise AiUnavailableError("Advisory drafting needs GEMINI_API_KEY")
        alert = self.repository.get_alert(alert_id)
        if alert is None:
            raise AlertNotFoundError(alert_id)
        if audience not in KNOWN_AUDIENCES:
            raise ValueError(f"Unknown audience {audience!r}; expected one of {KNOWN_AUDIENCES}")

        observation = self.repository.get_observation(alert.observation_id)
        history = [
            item
            for item in self.repository.observation_summaries(limit=50, site_code=alert.site_code)
            if item["observation_id"] != alert.observation_id
        ][:10]

        briefing = self.briefing_writer.draft(
            alert=alert,
            audience=audience,
            policy_id=self.thresholds.policy_id,
            policy_status=self.thresholds.status,
            observation=observation,
            site_history=history,
        )
        self.repository.save_briefing(briefing)
        self.repository.append_provenance(
            "briefing-drafted",
            briefing.id,
            {
                "alert_id": alert.id,
                "audience": audience,
                "status": briefing.status,
                "ai": briefing.ai.model_dump(mode="json") if briefing.ai else None,
            },
        )
        return briefing

    def situation_report(self, limit: int = 100) -> SituationReport:
        if self.briefing_writer is None or not self.briefing_writer.available:
            raise AiUnavailableError("Situation reports need GEMINI_API_KEY")
        observations = self.repository.observation_summaries(limit=limit)
        alerts = [alert.model_dump(mode="json") for alert in self.repository.list_alerts(limit)]
        pending = self.repository.count_proposals_by_status().get(ReviewStatus.PENDING.value, 0)

        report = self.briefing_writer.situation_report(
            observations=observations,
            alerts=alerts,
            pending_count=pending,
            policy_id=self.thresholds.policy_id,
            policy_status=self.thresholds.status,
        )
        self.repository.append_provenance(
            "situation-report",
            report.ai.response_hash if report.ai else "no-attribution",
            {
                "observations_considered": report.observations_considered,
                "alerts_considered": report.alerts_considered,
                "pending_reviews": report.pending_reviews,
                "ai": report.ai.model_dump(mode="json") if report.ai else None,
            },
        )
        return report

    # -- internals ---------------------------------------------------------

    def _evaluate_and_store(self, observation: dict[str, Any]) -> list[Alert]:
        alerts = self.thresholds.evaluate(observation)
        for alert in alerts:
            if self.repository.save_alert(alert):
                self.repository.append_provenance(
                    "alert-created", alert.id, alert.model_dump(mode="json")
                )
        return alerts

    def _pending_proposal(self, proposal_id: str) -> MappingProposal:
        proposal = self.repository.get_proposal(proposal_id)
        if not proposal:
            raise ProposalNotFoundError(proposal_id)
        if proposal.status != ReviewStatus.PENDING:
            raise InvalidReviewStateError(
                f"Proposal is already {proposal.status.value}; decisions are immutable"
            )
        return proposal


def _reading_from_csv_row(row: dict[str, str]) -> RawReading:
    evidence = (row.get("evidence_url") or "").strip()
    return RawReading(
        source_id=row["source_id"],
        source_type=row["source_type"],
        parameter=row["parameter"],
        value=float(row["value"]),
        unit=row["unit"],
        observed_at=row["observed_at"],
        site_code=row["site_code"],
        site_name=row["site_name"],
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        evidence_url=evidence or None,
        raw_payload={"replay_source": "data/oder-replay.csv", "synthetic": True},
    )


__all__ = [
    "AiUnavailableError",
    "AlertNotFoundError",
    "BridgeService",
    "GeminiError",
    "InvalidReviewStateError",
    "ProposalNotFoundError",
]
