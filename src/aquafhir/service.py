from datetime import UTC, datetime, timedelta
from typing import Any

from aquafhir.coding import ReviewedCodingAgent
from aquafhir.fhir import (
    OAH_LOCATION_PROFILE,
    OAH_OBSERVATION_PROFILE,
    FhirClient,
    build_resources,
    transaction_bundle,
)
from aquafhir.models import (
    Alert,
    ApprovalResult,
    MappingProposal,
    RawReading,
    RejectDecision,
    ReviewDecision,
    ReviewStatus,
)
from aquafhir.repository import Repository
from aquafhir.thresholds import ThresholdPolicy


class ProposalNotFoundError(LookupError):
    pass


class InvalidReviewStateError(ValueError):
    pass


class BridgeService:
    def __init__(
        self,
        repository: Repository,
        coding_agent: ReviewedCodingAgent,
        thresholds: ThresholdPolicy,
        fhir_client: FhirClient,
    ) -> None:
        self.repository = repository
        self.coding_agent = coding_agent
        self.thresholds = thresholds
        self.fhir_client = fhir_client

    def propose(self, reading: RawReading) -> MappingProposal:
        proposal = self.coding_agent.propose(reading)
        self.repository.save_proposal(proposal)
        self.repository.append_provenance(
            "mapping-proposed", proposal.id, proposal.model_dump(mode="json")
        )
        return proposal

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
            {"reviewer": decision.reviewer, "observation_id": observation["id"]},
        )
        alerts = self._evaluate_and_store(observation)
        return ApprovalResult(
            proposal=proposal,
            observation=observation,
            fhir_response=fhir_response,
            alerts=alerts,
        )

    def reject(self, proposal_id: str, decision: RejectDecision) -> MappingProposal:
        proposal = self._pending_proposal(proposal_id)
        proposal.status = ReviewStatus.REJECTED
        proposal.reviewer = decision.reviewer
        proposal.reviewed_at = datetime.now(UTC)
        self.repository.save_proposal(proposal)
        self.repository.append_provenance(
            "mapping-rejected",
            proposal.id,
            {"reviewer": decision.reviewer, "reason": decision.reason},
        )
        return proposal

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
