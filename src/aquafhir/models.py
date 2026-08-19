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


class MappingProposal(BaseModel):
    id: str
    reading: RawReading
    coding: Coding | None
    normalized_value: float | None
    normalized_unit: str | None
    confidence: float = Field(ge=0, le=1)
    rationale: str
    status: ReviewStatus = ReviewStatus.PENDING
    requires_review: bool = True
    reviewer: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reviewed_at: datetime | None = None


class ReviewDecision(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    coding: Coding | None = None
    normalized_value: float | None = None
    normalized_unit: str | None = None

    @model_validator(mode="after")
    def quantity_override_is_complete(self) -> "ReviewDecision":
        if (self.normalized_value is None) != (self.normalized_unit is None):
            raise ValueError("normalized_value and normalized_unit must be supplied together")
        return self


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


class ApprovalResult(BaseModel):
    proposal: MappingProposal
    observation: dict[str, Any]
    fhir_response: dict[str, Any]
    alerts: list[Alert]


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
