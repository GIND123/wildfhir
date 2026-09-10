from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

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


class OneHealthLeg(StrEnum):
    """Which leg of One Health an indicator belongs to.

    The OAH IG publishes all three in one code system but binds them to two
    profiles: environmental and animal indicators go through
    `observation-indicators-oah`, human health measures through
    `observation-health-measure-oah`. The leg decides the profile.
    """

    ENVIRONMENTAL = "environmental"
    ANIMAL = "animal"
    HUMAN = "human"


class RawReading(BaseModel):
    """One measurement as the source reported it.

    A reading carries either a numeric `value` with its `unit`, or a
    `coded_value`: the word a citizen-science app or a field sheet used
    ("present", "extensive", "none"). Never both. The OAH IG models foam,
    macrophytes and the ordinal indicators as coded values, not quantities,
    and forcing them through a float would invent a number the source never
    reported.
    """

    source_id: str = Field(min_length=1, max_length=120)
    source_type: SourceType
    parameter: str = Field(min_length=1, max_length=200)
    # allow_inf_nan=False: NaN/Infinity serialise to JSON null, which would
    # publish an Observation whose valueQuantity has no value at all.
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = Field(default="", max_length=40)
    coded_value: str | None = Field(default=None, max_length=120)
    observed_at: datetime
    site_code: str = Field(min_length=1, max_length=100)
    site_name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    evidence_url: HttpUrl | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def exactly_one_kind_of_value(self) -> "RawReading":
        coded = (self.coded_value or "").strip()
        if self.value is None and not coded:
            raise ValueError("A reading needs either a numeric value or a coded_value")
        if self.value is not None and coded:
            raise ValueError("A reading carries a numeric value or a coded_value, not both")
        if self.value is not None and not self.unit.strip():
            raise ValueError("A numeric value needs the unit the source wrote")
        if coded:
            self.coded_value = coded
        return self

    @property
    def is_coded(self) -> bool:
        return self.coded_value is not None


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


class UnitSuggestion(BaseModel):
    id: str
    code: str
    interpreted_unit: str = Field(min_length=1, max_length=120)
    normalized_unit: str = Field(min_length=1, max_length=40)
    normalized_value: float = Field(allow_inf_nan=False)
    factor: float = Field(gt=0, allow_inf_nan=False)
    offset: float = Field(default=0, allow_inf_nan=False)
    formula: str
    rationale: str = Field(min_length=1, max_length=1000)
    ai: AiAttribution
    origin: Literal["ai-interpretation", "ai-conversion"]
    evidence_status: Literal["uncited"] = "uncited"


class UnitSuggestionResult(BaseModel):
    status: Literal["suggested", "no-match", "unavailable"]
    suggestion: UnitSuggestion | None = None
    message: str


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
    taxon: Coding | None = None
    normalized_value: float | None
    normalized_unit: str | None
    # The reviewed value-set concept a coded reading resolved to. A coded
    # indicator publishes this as `valueCodeableConcept` instead of a quantity.
    normalized_coding: Coding | None = None
    # Which One Health leg the proposed code belongs to; decides the profile.
    leg: OneHealthLeg = OneHealthLeg.ENVIRONMENTAL
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
    # The audit record for the model call behind this proposal, successful or
    # not. Present even when `ai` is None, which is how the console can tell
    # "rules resolved it" apart from "the model was tried and failed".
    ai_audit: dict[str, Any] | None = None
    # Set only when a reviewer overrode the deterministic conversion.
    correction_reason: str | None = None
    # Id of an earlier proposal carrying an identical reading, if any.
    duplicate_of: str | None = None
    unit_suggestions: dict[str, UnitSuggestionResult] = Field(default_factory=dict)

    @property
    def has_publishable_value(self) -> bool:
        """A quantity with a UCUM unit, or a reviewed coded value."""
        quantity = self.normalized_value is not None and bool(self.normalized_unit)
        return quantity or self.normalized_coding is not None


class ReviewDecision(BaseModel):
    """What a reviewer decided. Note what it deliberately cannot carry.

    `coding` selects which catalog concept to publish, and **only its `code` is
    read**. The published system and display text always come from the reviewed
    catalog, so a client cannot mint a coding of its own.

    Supplying a quantity or a coded value is an *expert correction*, not a
    routine field. It means "the deterministic resolution is wrong or
    impossible, and here is what to publish instead", so it requires a written
    reason and is still checked against the selected rule's accepted units,
    plausible range, or value set. Ordinary approvals send none of these: the
    server derives the published value.
    """

    reviewer: str = Field(min_length=1, max_length=120)
    coding: Coding | None = None
    normalized_value: float | None = Field(default=None, allow_inf_nan=False)
    normalized_unit: str | None = None
    # For a coded indicator: the value-set code to publish instead of the
    # one the proposer resolved (or failed to resolve).
    coded_value: str | None = Field(default=None, max_length=120)
    correction_reason: str | None = Field(default=None, max_length=500)
    unit_suggestion_id: str | None = Field(default=None, max_length=120)
    secondary_coding: Coding | None = None
    # A GBIF Backbone taxon the reviewer chose from the biodiversity crosswalk.
    # Like `secondary_coding`, it is never inferred: no taxon reaches FHIR
    # unless a person picked it here.
    taxon: Coding | None = None

    @property
    def is_correction(self) -> bool:
        return self.normalized_value is not None or bool((self.coded_value or "").strip())

    @model_validator(mode="after")
    def expert_correction_is_complete(self) -> "ReviewDecision":
        """A correction is a value and a reason together, or none of them.

        Allowing a value without a reason is how an unexplained number reaches
        FHIR; allowing a reason without a value records an intent that never
        happened.
        """
        coded = bool((self.coded_value or "").strip())
        quantity = {
            "normalized_value": self.normalized_value is not None,
            "normalized_unit": self.normalized_unit is not None,
        }
        reason = bool((self.correction_reason or "").strip())
        if self.unit_suggestion_id and not all({**quantity, "correction_reason": reason}.values()):
            raise ValueError(
                "Accepting an AI unit suggestion requires a complete expert correction"
            )
        if coded and any(quantity.values()):
            raise ValueError(
                "An expert correction replaces either the quantity or the coded value, not both"
            )
        if coded:
            if not reason:
                raise ValueError(
                    "An expert correction needs coded_value and correction_reason together; "
                    "missing: correction_reason"
                )
            self.coded_value = self.coded_value.strip()
            return self
        supplied = {**quantity, "correction_reason": reason}
        if any(supplied.values()) and not all(supplied.values()):
            missing = sorted(name for name, present in supplied.items() if not present)
            raise ValueError(
                "An expert correction needs normalized_value, normalized_unit and "
                f"correction_reason together; missing: {', '.join(missing)}"
            )
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
    # A quantity rule fills value/unit; a coded rule fills value_code.
    value: float | None = None
    unit: str = ""
    value_code: str | None = None
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
    ai_audit: dict[str, Any] | None = None
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
    ai_audit: dict[str, Any] | None = None
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
    ai_audit: dict[str, Any] | None = None


class AcceptedValue(BaseModel):
    """One concept a coded indicator may publish, from the IG's value set."""

    code: str
    display: str
    aliases: list[str] = Field(default_factory=list)


class NormalizationPreview(BaseModel):
    """What the server would publish for one proposal under one catalog code.

    Display-only. The reviewer never sends these numbers back: approval
    recomputes them, so the dialog and the published resource cannot drift.
    """

    code: str
    display: str
    system: str
    leg: OneHealthLeg = OneHealthLeg.ENVIRONMENTAL
    # quantity | coded -- what the *reading* carries.
    value_kind: str = "quantity"
    source_value: float | None = None
    source_unit: str = ""
    source_coded_value: str | None = None
    accepted_units: list[str] = Field(default_factory=list)
    conversion_origin: Literal["reviewed-catalog", "reviewed-alias", "none"] = "none"
    interpreted_unit: str | None = None
    ai_result: UnitSuggestionResult | None = None
    ai_available: bool = False
    accepted_values: list[AcceptedValue] = Field(default_factory=list)
    plausible_range: dict[str, float] | None = None
    # ok | unit-unresolved | out-of-range | value-unresolved | kind-mismatch
    status: str
    normalized_value: float | None = None
    normalized_unit: str | None = None
    normalized_coding: Coding | None = None
    factor: float | None = None
    formula: str | None = None
    message: str


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
    """Whether the AI layer is configured, and whether it is actually working.

    `configured` means only that a key is present. `health` reports what the
    last real call did, because a present key says nothing about quota,
    credentials or reachability.
    """

    enabled: bool
    configured: bool = False
    # unknown (no call yet) | ok | quota-exceeded | auth-failed | timeout | upstream-error
    health: str = "unknown"
    last_call: dict[str, Any] | None = None
    provider: str = "google-gemini"
    model: str
    # The model configured as the automatic stand-in for a 429/404, if any.
    fallback_model: str | None = None
    assist_mode: str
    assist_below_confidence: float
    confidence_ceiling: float
    features: list[str] = Field(default_factory=list)
    detail: str


class UmlsStatus(BaseModel):
    enabled: bool
    provider: str = "nlm-umls-uts"
    sources: list[str] = Field(default_factory=list)
    vocabularies: list[str] = Field(default_factory=list)
    detail: str


# -- live connectors ---------------------------------------------------------


class SceneCandidate(BaseModel):
    """One Sentinel-2 product from the Copernicus catalogue covering a site."""

    product_id: str
    name: str
    sensed_at: datetime
    cloud_cover: float | None = None
    tile_id: str | None = None
    product_type: str | None = None
    online: bool | None = None
    catalogue_url: str


class ConnectorPullRequest(BaseModel):
    """Parameters for one pull from a live connector."""

    # Hub'Eau: station codes from config/connectors.yaml (default: all).
    stations: list[str] = Field(default_factory=list, max_length=20)
    # Sentinel-2: a site code from config/connectors.yaml.
    site_code: str | None = Field(default=None, max_length=100)
    days: int = Field(default=365, ge=1, le=3660)
    max_cloud: float = Field(default=40.0, ge=0, le=100)
    limit: int = Field(default=50, ge=1, le=500)


class ConnectorPullResult(BaseModel):
    connector: str
    source_id: str
    fetched: int
    skipped: list[str] = Field(default_factory=list)
    proposals: list[MappingProposal] = Field(default_factory=list)
    # SHA-256 of the exact upstream request, so the provenance chain can pin
    # which query produced these readings.
    request_hash: str
    request_url: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConnectorStatus(BaseModel):
    name: str
    provider: str
    enabled: bool
    # keyless | credentials-required | credentials-configured
    auth: str
    live: bool
    detail: str
    api_base: str
    sites: list[dict[str, Any]] = Field(default_factory=list)
