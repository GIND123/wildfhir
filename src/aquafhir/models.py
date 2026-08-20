from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator


class SourceType(StrEnum):
    AGENCY = "agency"
    CITIZEN = "citizen"
    SATELLITE = "satellite"
    WEATHER = "weather"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProposerKind(StrEnum):
    """Which proposer produced a mapping. Never affects review requirements."""

    CURATED = "curated-rules"
    GEMINI_ASSISTED = "gemini-assisted"


class RawReading(BaseModel):
    source_id: str = Field(min_length=1, max_length=120)
    source_type: SourceType
    parameter: str = Field(min_length=1, max_length=200)
    value: float
    unit: str = Field(min_length=1, max_length=40)
    observed_at: datetime
    site_code: str = Field(min_length=1, max_length=100)
    site_name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    evidence_url: HttpUrl | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class Coding(BaseModel):
    system: str
    code: str
    display: str


class AiAttribution(BaseModel):
    """Everything an auditor needs to reconstruct one model call."""

    provider: str = "google-gemini"
    model: str
    template_id: str
    prompt_hash: str
    response_hash: str
    latency_ms: int
    grounded_codes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    model_confidence: float | None = None
    disagreed_with_rules: bool = False
    needs_expert_review: bool = False


class CandidateCoding(BaseModel):
    code: str
    display: str
    score: float
    origin: str


class TerminologyMatch(BaseModel):
    """One UMLS-suggested real-world code for a curated OAH display term.

    A suggestion only -- see `ReviewDecision.secondary_coding`. Nothing in
    this pipeline ever attaches one without an explicit reviewer choice.
    """

    system: str
    code: str
    display: str
    vocabulary: str
    score: float


class MappingProposal(BaseModel):
    id: str
    reading: RawReading
    coding: Coding | None
    secondary_coding: Coding | None = None
    normalized_value: float | None
    normalized_unit: str | None
    confidence: float = Field(ge=0, le=1)
    rationale: str
    status: ReviewStatus = ReviewStatus.PENDING
    requires_review: bool = True
    reviewer: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reviewed_at: datetime | None = None
    proposer: ProposerKind = ProposerKind.CURATED
    candidates: list[CandidateCoding] = Field(default_factory=list)
    ai: AiAttribution | None = None


class ReviewDecision(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    coding: Coding | None = None
    normalized_value: float | None = None
    normalized_unit: str | None = None
    secondary_coding: Coding | None = None

    @model_validator(mode="after")
    def quantity_override_is_complete(self) -> "ReviewDecision":
        if (self.normalized_value is None) != (self.normalized_unit is None):
            raise ValueError("normalized_value and normalized_unit must be supplied together")
        return self


class BatchReviewDecision(BaseModel):
    """Approve several inspected proposals under one named reviewer.

    Each id is still decided, stored, and hash-chained individually, so a batch
    sign-off is not a shortcut around the review state machine.
    """

    reviewer: str = Field(min_length=1, max_length=120)
    proposal_ids: list[str] = Field(min_length=1, max_length=100)


class RejectDecision(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=500)


class Alert(BaseModel):
    id: str
    observation_id: str
    policy_id: str
    rule_code: str
    severity: str
    message: str
    audiences: list[str]
    value: float
    unit: str
    site_code: str
    observed_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AlertBriefing(BaseModel):
    """An AI-drafted, human-approved-before-use advisory for one audience."""

    id: str
    alert_id: str
    audience: str
    headline: str
    summary: str
    recommended_actions: list[str]
    uncertainty: str
    escalation_question: str
    status: str = "draft"
    disclaimer: str = (
        "AI-drafted decision support. Not a public warning, clinical advice, or "
        "veterinary advice. An accountable authority must review before any use."
    )
    ai: AiAttribution | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SiteAssessment(BaseModel):
    site_code: str
    assessment: str


class SituationReport(BaseModel):
    headline: str
    situation: str
    by_site: list[SiteAssessment] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    observations_considered: int = 0
    alerts_considered: int = 0
    pending_reviews: int = 0
    disclaimer: str = (
        "Generated from this bridge's own stored records only. No external data, "
        "no prediction, no regulatory determination."
    )
    ai: AiAttribution | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IntakeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    source_id: str = Field(default="unstructured-intake", min_length=1, max_length=120)
    source_type: SourceType = SourceType.AGENCY
    default_site_code: str = Field(default="unknown-site", min_length=1, max_length=100)
    default_site_name: str = Field(default="Unknown site", min_length=1, max_length=200)
    default_latitude: float = Field(default=52.5887, ge=-90, le=90)
    default_longitude: float = Field(default=14.6495, ge=-180, le=180)


class IntakeResult(BaseModel):
    proposals: list[MappingProposal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    extracted_count: int = 0
    rejected_count: int = 0
    ai: AiAttribution | None = None


class ApprovalResult(BaseModel):
    proposal: MappingProposal
    observation: dict[str, Any]
    fhir_response: dict[str, Any]
    alerts: list[Alert]


class BatchApprovalResult(BaseModel):
    approved: list[ApprovalResult] = Field(default_factory=list)
    failures: list[dict[str, str]] = Field(default_factory=list)


class ProvenanceEntry(BaseModel):
    sequence: int
    event_type: str
    entity_id: str
    payload: dict[str, Any]
    previous_hash: str
    hash: str
    created_at: datetime


class ChainVerification(BaseModel):
    valid: bool
    entries_checked: int
    first_invalid_sequence: int | None = None


class AiStatus(BaseModel):
    enabled: bool
    provider: str = "google-gemini"
    model: str
    assist_mode: str
    assist_below_confidence: float
    confidence_ceiling: float
    features: list[str] = Field(default_factory=list)
    detail: str


class UmlsStatus(BaseModel):
    enabled: bool
    provider: str = "nlm-umls-uts"
    vocabularies: list[str] = Field(default_factory=list)
    detail: str
