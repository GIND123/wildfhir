import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from aquafhir.briefing import KNOWN_AUDIENCES, BriefingWriter
from aquafhir.coding import CodingProposer, ReviewedCodingAgent
from aquafhir.coding_llm import GeminiCodingAgent
from aquafhir.config import Settings, get_settings
from aquafhir.fhir import FhirClient
from aquafhir.gemini import GeminiClient, GeminiError
from aquafhir.intake import UnstructuredIntake
from aquafhir.loinc_table import LoincTable
from aquafhir.models import (
    AiStatus,
    Alert,
    AlertBriefing,
    ApprovalResult,
    BatchApprovalResult,
    BatchReviewDecision,
    ChainVerification,
    IntakeRequest,
    IntakeResult,
    MappingProposal,
    ProvenanceEntry,
    RawReading,
    RejectDecision,
    ReviewDecision,
    SituationReport,
    TerminologyMatch,
    UmlsStatus,
)
from aquafhir.repository import Repository
from aquafhir.service import (
    AiUnavailableError,
    AlertNotFoundError,
    BridgeService,
    InvalidReviewStateError,
    ProposalNotFoundError,
)
from aquafhir.terminology import TerminologyCrosswalk
from aquafhir.thresholds import ThresholdPolicy
from aquafhir.umls import UMLSClient, UMLSError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_gemini_client(settings: Settings) -> GeminiClient:
    return GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        api_base=settings.gemini_api_base,
        timeout=settings.gemini_timeout_seconds,
        max_output_tokens=settings.gemini_max_output_tokens,
        max_retries=settings.gemini_max_retries,
        thinking_budget=settings.gemini_thinking_budget,
    )


def build_coding_agent(settings: Settings, gemini: GeminiClient) -> CodingProposer:
    """Curated rules always load. Gemini wraps them only when a key is present."""
    curated = ReviewedCodingAgent(
        settings.coding_rules_path, settings.review_confidence_threshold
    )
    if not gemini.enabled:
        logger.info("GEMINI_API_KEY not set; running the deterministic coding agent only")
        return curated
    logger.info(
        "Gemini coding co-pilot enabled (model=%s, mode=%s)",
        settings.gemini_model,
        settings.gemini_assist_mode.value,
    )
    return GeminiCodingAgent(
        curated,
        gemini,
        assist_mode=settings.gemini_assist_mode,
        assist_below_confidence=settings.gemini_assist_below_confidence,
        confidence_ceiling=settings.gemini_confidence_ceiling,
    )


def build_umls_client(settings: Settings) -> UMLSClient:
    return UMLSClient(
        api_key=settings.umls_api_key,
        api_base=settings.umls_api_base,
        timeout=settings.umls_timeout_seconds,
        max_retries=settings.umls_max_retries,
    )


def build_service(settings: Settings) -> BridgeService:
    gemini = build_gemini_client(settings)
    umls = build_umls_client(settings)
    if not umls.enabled:
        logger.info("UMLS_API_KEY not set; terminology crosswalk suggestions are disabled")
    return BridgeService(
        repository=Repository(settings.database_path),
        coding_agent=build_coding_agent(settings, gemini),
        thresholds=ThresholdPolicy(settings.thresholds_path),
        fhir_client=FhirClient(
            settings.fhir_base_url,
            settings.fhir_write_enabled,
            settings.fhir_timeout_seconds,
        ),
        intake=UnstructuredIntake(gemini),
        briefing_writer=BriefingWriter(gemini),
        terminology=TerminologyCrosswalk(
            umls,
            vocabularies=tuple(settings.umls_vocabulary_list),
            loinc_table=LoincTable(settings.loinc_table_path),
        ),
        replay_path=settings.replay_data_path,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = build_service(get_settings())
    yield


app = FastAPI(
    title="AquaFHIR Bridge",
    version="0.2.0",
    description=(
        "Reviewed environmental-to-FHIR normalization, Gemini-assisted terminology "
        "coding, and audience-routed alerting. Every AI output is a proposal that a "
        "human must approve before publication."
    ),
    lifespan=lifespan,
)


@app.exception_handler(AiUnavailableError)
async def ai_unavailable_handler(_: Request, error: AiUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(GeminiError)
async def gemini_error_handler(_: Request, error: GeminiError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": f"Gemini upstream failure: {error}"},
    )


@app.exception_handler(UMLSError)
async def umls_error_handler(_: Request, error: UMLSError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": f"UMLS upstream failure: {error}"},
    )


def get_service(request: Request) -> BridgeService:
    return request.app.state.service


Service = Annotated[BridgeService, Depends(get_service)]


# -- status ----------------------------------------------------------------


@app.get("/api/v1/health")
def health(service: Service) -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "fhir_write_mode": "enabled" if settings.fhir_write_enabled else "dry-run",
        "threshold_policy": service.thresholds.policy_id,
        "threshold_policy_status": service.thresholds.status,
        "ai_mode": "gemini" if settings.gemini_enabled else "deterministic-only",
        "ai_model": settings.gemini_model if settings.gemini_enabled else None,
        "terminology_crosswalk": "+".join(service.terminology.sources())
        if service.terminology and service.terminology.available
        else "off",
    }


@app.get("/api/v1/ai/status", response_model=AiStatus)
def ai_status(service: Service) -> AiStatus:
    settings = get_settings()
    enabled = settings.gemini_enabled
    return AiStatus(
        enabled=enabled,
        model=settings.gemini_model,
        assist_mode=settings.gemini_assist_mode.value if enabled else "off",
        assist_below_confidence=settings.gemini_assist_below_confidence,
        confidence_ceiling=settings.gemini_confidence_ceiling,
        features=(
            [
                "terminology-coding-copilot",
                "unstructured-intake",
                "audience-advisory-drafting",
                "grounded-situation-report",
            ]
            if enabled
            else []
        ),
        detail=(
            "Gemini proposes; a human reviewer approves. No model output is published "
            "to FHIR, and no model output changes an alert decision."
            if enabled
            else "GEMINI_API_KEY is not set. The deterministic pipeline is fully functional."
        ),
    )


@app.get("/api/v1/terminology/status", response_model=UmlsStatus)
def terminology_status(service: Service) -> UmlsStatus:
    settings = get_settings()
    crosswalk = service.terminology
    sources = crosswalk.sources() if crosswalk else []
    enabled = bool(crosswalk and crosswalk.available)
    if "loinc-table" in sources and "umls" in sources:
        detail = (
            "Environmental LOINC terms are matched locally against the published "
            "LOINC table; UMLS UTS tops up the rest, including SNOMED CT. Both only "
            "ever suggest a second coding for a reviewer to attach at approval time."
        )
    elif "loinc-table" in sources:
        detail = (
            "Local LOINC table only (UMLS_API_KEY unset). Environmental LOINC "
            "suggestions work offline; SNOMED CT candidates are unavailable."
        )
    elif "umls" in sources:
        detail = (
            "UMLS UTS only (the LOINC table is missing). LOINC hits cannot be "
            "validated against the published term list."
        )
    else:
        detail = (
            "No terminology source configured. The OAH coding and FHIR pipeline is "
            "unaffected; approved Observations simply carry one coding."
        )
    return UmlsStatus(
        enabled=enabled,
        sources=sources,
        vocabularies=settings.umls_vocabulary_list if enabled else [],
        detail=detail,
    )


# -- ingestion and review --------------------------------------------------


@app.post("/api/v1/proposals", response_model=MappingProposal, status_code=status.HTTP_201_CREATED)
def create_proposal(reading: RawReading, service: Service) -> MappingProposal:
    return service.propose(reading)


@app.get("/api/v1/proposals", response_model=list[MappingProposal])
def list_proposals(
    service: Service, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[MappingProposal]:
    return service.repository.list_proposals(limit)


@app.post(
    "/api/v1/replay",
    response_model=list[MappingProposal],
    status_code=status.HTTP_201_CREATED,
    summary="Load the synthetic Oder timeline as pending proposals",
)
def replay_dataset(service: Service) -> list[MappingProposal]:
    try:
        return service.replay()
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post(
    "/api/v1/intake",
    response_model=IntakeResult,
    status_code=status.HTTP_201_CREATED,
    summary="Extract readings from an unstructured note (Gemini)",
)
def ingest_unstructured(request_body: IntakeRequest, service: Service) -> IntakeResult:
    return service.ingest_unstructured(request_body)


@app.post(
    "/api/v1/proposals/approve-batch",
    response_model=BatchApprovalResult,
    summary="Sign off several inspected proposals under one reviewer",
)
def approve_batch(decision: BatchReviewDecision, service: Service) -> BatchApprovalResult:
    return service.approve_batch(decision)


@app.get("/api/v1/proposals/{proposal_id}", response_model=MappingProposal)
def get_proposal(proposal_id: str, service: Service) -> MappingProposal:
    proposal = service.repository.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@app.get(
    "/api/v1/proposals/{proposal_id}/terminology-suggestions",
    response_model=list[TerminologyMatch],
    summary="Suggest a real LOINC/SNOMED CT crosswalk for a proposal's OAH code (UMLS)",
)
def terminology_suggestions(proposal_id: str, service: Service) -> list[TerminologyMatch]:
    try:
        return service.suggest_terminology(proposal_id)
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail="Proposal not found") from error


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


# -- alerts and advisories -------------------------------------------------


@app.get("/api/v1/alerts", response_model=list[Alert])
def list_alerts(
    service: Service, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[Alert]:
    return service.repository.list_alerts(limit)


@app.get("/api/v1/briefings", response_model=list[AlertBriefing])
def list_briefings(
    service: Service, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[AlertBriefing]:
    return service.repository.list_briefings(limit=limit)


@app.get("/api/v1/alerts/{alert_id}/briefings", response_model=list[AlertBriefing])
def list_alert_briefings(alert_id: str, service: Service) -> list[AlertBriefing]:
    return service.repository.list_briefings(alert_id=alert_id)


@app.post(
    "/api/v1/alerts/{alert_id}/briefings",
    response_model=AlertBriefing,
    status_code=status.HTTP_201_CREATED,
    summary="Draft an audience-specific advisory for an alert (Gemini)",
)
def draft_briefing(
    alert_id: str,
    service: Service,
    audience: Annotated[str, Query(description=f"One of {', '.join(KNOWN_AUDIENCES)}")],
) -> AlertBriefing:
    try:
        return service.draft_briefing(alert_id, audience)
    except AlertNotFoundError as error:
        raise HTTPException(status_code=404, detail="Alert not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post(
    "/api/v1/ai/situation-report",
    response_model=SituationReport,
    summary="Summarise stored observations and alerts (Gemini, grounded)",
)
def situation_report(
    service: Service, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> SituationReport:
    return service.situation_report(limit)


# -- provenance ------------------------------------------------------------


@app.get("/api/v1/provenance", response_model=list[ProvenanceEntry])
def list_provenance(
    service: Service, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[ProvenanceEntry]:
    return service.repository.list_provenance(limit)


@app.get("/api/v1/provenance/verify", response_model=ChainVerification)
def verify_provenance(service: Service) -> ChainVerification:
    return service.repository.verify_chain()


# -- FHIR subscription plumbing --------------------------------------------


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
