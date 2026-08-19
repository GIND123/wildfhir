from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aquafhir.coding import ReviewedCodingAgent
from aquafhir.config import Settings, get_settings
from aquafhir.fhir import FhirClient
from aquafhir.models import (
    Alert,
    ApprovalResult,
    ChainVerification,
    MappingProposal,
    ProvenanceEntry,
    RawReading,
    RejectDecision,
    ReviewDecision,
)
from aquafhir.repository import Repository
from aquafhir.service import BridgeService, InvalidReviewStateError, ProposalNotFoundError
from aquafhir.thresholds import ThresholdPolicy


def build_service(settings: Settings) -> BridgeService:
    return BridgeService(
        repository=Repository(settings.database_path),
        coding_agent=ReviewedCodingAgent(
            settings.coding_rules_path, settings.review_confidence_threshold
        ),
        thresholds=ThresholdPolicy(settings.thresholds_path),
        fhir_client=FhirClient(
            settings.fhir_base_url,
            settings.fhir_write_enabled,
            settings.fhir_timeout_seconds,
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = build_service(get_settings())
    yield


app = FastAPI(
    title="AquaFHIR Bridge",
    version="0.1.0",
    description="Reviewed environmental-to-FHIR normalization and alerting pipeline.",
    lifespan=lifespan,
)


def get_service(request: Request) -> BridgeService:
    return request.app.state.service


Service = Annotated[BridgeService, Depends(get_service)]


@app.get("/api/v1/health")
def health(service: Service) -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "fhir_write_mode": "enabled" if settings.fhir_write_enabled else "dry-run",
        "threshold_policy": service.thresholds.policy_id,
        "threshold_policy_status": service.thresholds.status,
    }


@app.post("/api/v1/proposals", response_model=MappingProposal, status_code=status.HTTP_201_CREATED)
def create_proposal(reading: RawReading, service: Service) -> MappingProposal:
    return service.propose(reading)


@app.get("/api/v1/proposals", response_model=list[MappingProposal])
def list_proposals(
    service: Service, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[MappingProposal]:
    return service.repository.list_proposals(limit)


@app.get("/api/v1/proposals/{proposal_id}", response_model=MappingProposal)
def get_proposal(proposal_id: str, service: Service) -> MappingProposal:
    proposal = service.repository.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@app.post("/api/v1/proposals/{proposal_id}/approve", response_model=ApprovalResult)
def approve_proposal(
    proposal_id: str, decision: ReviewDecision, service: Service
) -> ApprovalResult:
    try:
        return service.approve(proposal_id, decision)
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail="Proposal not found") from error
    except InvalidReviewStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/v1/proposals/{proposal_id}/reject", response_model=MappingProposal)
def reject_proposal(
    proposal_id: str, decision: RejectDecision, service: Service
) -> MappingProposal:
    try:
        return service.reject(proposal_id, decision)
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail="Proposal not found") from error
    except InvalidReviewStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/v1/alerts", response_model=list[Alert])
def list_alerts(
    service: Service, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[Alert]:
    return service.repository.list_alerts(limit)


@app.get("/api/v1/provenance", response_model=list[ProvenanceEntry])
def list_provenance(
    service: Service, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[ProvenanceEntry]:
    return service.repository.list_provenance(limit)


@app.get("/api/v1/provenance/verify", response_model=ChainVerification)
def verify_provenance(service: Service) -> ChainVerification:
    return service.repository.verify_chain()


@app.post("/api/v1/subscriptions")
def install_subscription(callback_url: str, service: Service) -> dict[str, Any]:
    settings = get_settings()
    return service.fhir_client.install_subscription(
        callback_url, settings.webhook_shared_secret
    )


@app.post("/api/v1/webhooks/fhir")
def receive_fhir_webhook(
    service: Service,
    x_aquafhir_secret: Annotated[str | None, Header()] = None,
    resource: Annotated[dict[str, Any] | None, Body()] = None,
) -> dict[str, Any]:
    if x_aquafhir_secret != get_settings().webhook_shared_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    if resource is not None:
        alerts = service.process_webhook_observation(resource)
        return {"mode": "resource", "observations_processed": 1, "alerts": alerts}
    processed, alerts = service.process_subscription_notification()
    return {"mode": "r4-rest-hook", "observations_processed": processed, "alerts": alerts}


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def run() -> None:
    settings = get_settings()
    uvicorn.run("aquafhir.main:app", host=settings.app_host, port=settings.app_port, reload=False)
