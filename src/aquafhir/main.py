import logging
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from aquafhir.briefing import KNOWN_AUDIENCES, BriefingWriter
from aquafhir.coding import CodingProposer, ReviewedCodingAgent
from aquafhir.coding_llm import GeminiCodingAgent
from aquafhir.config import Settings, get_settings
from aquafhir.connectors import (
    HUBEAU_PARAMETERS,
    ConnectorError,
    ConnectorUnavailableError,
    CopernicusClient,
    HubEauClient,
    load_connector_config,
)
from aquafhir.fhir import (
    OAH_HEALTH_MEASURE_PROFILE,
    OAH_LOCATION_PROFILE,
    OAH_OBSERVATION_PROFILE,
    FhirClient,
)
from aquafhir.gbif import GbifClient, GbifError
from aquafhir.gemini import GeminiClient, GeminiError
from aquafhir.gemini import safe_message as gemini_safe_message
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
    ConnectorPullRequest,
    ConnectorPullResult,
    ConnectorStatus,
    IncidentRunReport,
    IntakeRequest,
    IntakeResult,
    MappingProposal,
    NormalizationPreview,
    ProvenanceEntry,
    RawReading,
    RejectDecision,
    ReviewDecision,
    SceneCandidate,
    SituationReport,
    TerminologyMatch,
    UmlsStatus,
    UnitSuggestionResult,
)
from aquafhir.repository import Repository
from aquafhir.service import (
    AiUnavailableError,
    AlertNotFoundError,
    ApprovalValidationError,
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
        fallback_model=settings.gemini_fallback_model,
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


def build_gbif_client(settings: Settings) -> GbifClient:
    return GbifClient(
        enabled=settings.gbif_enabled,
        api_base=settings.gbif_api_base,
        timeout=settings.gbif_timeout_seconds,
        max_retries=settings.gbif_max_retries,
    )


def build_hubeau_client(settings: Settings, source_id: str) -> HubEauClient:
    return HubEauClient(
        enabled=settings.hubeau_enabled,
        api_base=settings.hubeau_api_base,
        timeout=settings.hubeau_timeout_seconds,
        max_retries=settings.hubeau_max_retries,
        source_id=source_id,
    )


def build_copernicus_client(settings: Settings, source_id: str) -> CopernicusClient:
    return CopernicusClient(
        enabled=settings.sentinel2_enabled,
        client_id=settings.cdse_client_id,
        client_secret=settings.cdse_client_secret,
        catalogue_base=settings.cdse_catalogue_base,
        statistics_url=settings.cdse_statistics_url,
        token_url=settings.cdse_token_url,
        timeout=settings.cdse_timeout_seconds,
        max_retries=settings.cdse_max_retries,
        source_id=source_id,
    )


def build_service(settings: Settings) -> BridgeService:
    gemini = build_gemini_client(settings)
    umls = build_umls_client(settings)
    if not umls.enabled:
        logger.info("UMLS_API_KEY not set; terminology crosswalk suggestions are disabled")
    connectors = (
        load_connector_config(settings.connectors_path)
        if settings.connectors_path.exists()
        else {"hubeau": {"stations": []}, "sentinel2": {"sites": []}}
    )
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
            gbif=build_gbif_client(settings),
        ),
        replay_path=settings.replay_data_path,
        incidents_path=settings.incidents_data_path,
        gemini=gemini,
        hubeau=build_hubeau_client(
            settings, connectors.get("hubeau", {}).get("source_id", "hubeau-naiades")
        ),
        copernicus=build_copernicus_client(
            settings,
            connectors.get("sentinel2", {}).get("source_id", "copernicus-sentinel2-l2a"),
        ),
        connector_config=connectors,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.service = build_service(settings)
    if settings.seed_demo_board:
        try:
            counts = app.state.service.seed_demo_board()
        except Exception:  # a failed seed must never keep the console from starting
            logger.exception("Seeding the demo board failed; starting with what is stored")
        else:
            logger.info("Demo board seed: %s", counts)
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


def _json_safe(value: Any) -> Any:
    """Replace values `json.dumps(allow_nan=False)` refuses with a printable string.

    A validation error echoes the offending input back to the caller. When that
    input is NaN or +/-Infinity -- which JSON cannot represent -- rendering the
    422 raises, and the client gets an opaque 500 instead of the field-level
    reason it should have got.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, error: RequestValidationError) -> JSONResponse:
    # jsonable_encoder first: `ctx` can hold a live exception object.
    # _json_safe second: the encoder leaves NaN/Infinity as floats.
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe(jsonable_encoder(error.errors()))},
    )


@app.exception_handler(ApprovalValidationError)
async def approval_validation_handler(
    _: Request, error: ApprovalValidationError
) -> JSONResponse:
    """422: the decision itself cannot be published. Nothing was written."""
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.exception_handler(AiUnavailableError)
async def ai_unavailable_handler(_: Request, error: AiUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(ConnectorUnavailableError)
async def connector_unavailable_handler(
    _: Request, error: ConnectorUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(ConnectorError)
async def connector_error_handler(_: Request, error: ConnectorError) -> JSONResponse:
    logger.warning("Connector call failed: %s", error, exc_info=True)
    return JSONResponse(
        status_code=502,
        content={
            "detail": "The upstream data service could not be reached or refused the request.",
            "error_code": "connector-upstream-error",
        },
    )


@app.exception_handler(GeminiError)
async def gemini_error_handler(_: Request, error: GeminiError) -> JSONResponse:
    """502 with a short category, never the provider's response body.

    The exception text carries up to 300 characters of whatever Gemini
    returned. That is useful in a log and unsafe in an HTTP response.
    """
    logger.warning("Gemini call failed: %s", error, exc_info=True)
    return JSONResponse(
        status_code=502,
        content={
            "detail": gemini_safe_message(error),
            "error_code": getattr(error, "category", "upstream-error"),
        },
    )


@app.exception_handler(GbifError)
async def gbif_error_handler(_: Request, error: GbifError) -> JSONResponse:
    logger.warning("GBIF call failed: %s", error, exc_info=True)
    return JSONResponse(
        status_code=502,
        content={
            "detail": "The GBIF taxonomy service could not be reached.",
            "error_code": "gbif-upstream-error",
        },
    )


@app.exception_handler(UMLSError)
async def umls_error_handler(_: Request, error: UMLSError) -> JSONResponse:
    logger.warning("UMLS call failed: %s", error, exc_info=True)
    return JSONResponse(
        status_code=502,
        content={
            "detail": "The UMLS terminology service could not be reached.",
            "error_code": "umls-upstream-error",
        },
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
        "ai_fallback_model": _effective_fallback(settings),
        "terminology_crosswalk": "+".join(service.terminology.sources())
        if service.terminology and service.terminology.available
        else "off",
        "connectors": [item.name for item in service.connector_statuses() if item.live],
    }


@app.get("/api/v1/ai/status", response_model=AiStatus)
def ai_status(service: Service) -> AiStatus:
    settings = get_settings()
    enabled = settings.gemini_enabled
    last = getattr(service.gemini, "last_call", None) if service.gemini else None
    if not enabled:
        health = "disabled"
    elif last is None:
        health = "unknown"
    elif last["outcome"] == "ok":
        health = "ok"
    else:
        health = last.get("category") or "upstream-error"
    return AiStatus(
        enabled=enabled,
        configured=enabled,
        health=health,
        last_call=last,
        model=settings.gemini_model,
        fallback_model=_effective_fallback(settings),
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
        detail=_ai_detail(enabled, health, last),
    )


_AI_HEALTH_DETAIL = {
    "unknown": (
        "A key is configured. No call has been made yet, so whether it works is unknown."
    ),
    "ok": "The last call succeeded.",
    "quota-exceeded": (
        "Gemini quota exceeded on the last call. Proposals are still saved using the "
        "rules fallback."
    ),
    "auth-failed": (
        "Gemini rejected the credentials on the last call. Check GEMINI_API_KEY."
    ),
    "timeout": "The last call timed out. Proposals fall back to the curated rules.",
    "upstream-error": (
        "The last call failed upstream. Proposals fall back to the curated rules."
    ),
}


def _ai_detail(enabled: bool, health: str, last: dict[str, Any] | None) -> str:
    """Say what is configured and, separately, what actually happened."""
    if not enabled:
        return "GEMINI_API_KEY is not set. The deterministic pipeline is fully functional."
    base = (
        "Gemini proposes; a human reviewer approves. No model output is published to "
        "FHIR, and no model output changes an alert decision."
    )
    note = _AI_HEALTH_DETAIL.get(health, _AI_HEALTH_DETAIL["upstream-error"])
    if last and last.get("at"):
        note = f"{note} Last call {last['at']}."
    return f"{base} {note}"


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
    if "gbif" in sources:
        detail += (
            " The GBIF Backbone crosswalk additionally suggests a taxon for an "
            "organism named in a source label; it is keyless and refuses cleanly "
            "on anything that is not an organism."
        )
    return UmlsStatus(
        enabled=enabled,
        sources=sources,
        vocabularies=settings.umls_vocabulary_list if enabled else [],
        detail=detail,
    )


def _effective_fallback(settings: Settings) -> str | None:
    """The fallback model that would actually be tried, or None.

    A fallback equal to the pinned model is a no-op, and reporting it as
    "falls back to itself" on the integrations page was misleading.
    """
    fallback = settings.gemini_fallback_model.strip()
    return fallback if fallback and fallback != settings.gemini_model else None


def _mask_secret(secret: str) -> str | None:
    """A fingerprint a reviewer can recognise, never the credential itself."""
    value = secret.strip()
    if not value:
        return None
    if len(value) <= 8:
        return "\u2022" * len(value)
    return f"{value[:4]}\u2026{value[-4:]}"


def _curated_agent(agent: CodingProposer) -> ReviewedCodingAgent | None:
    if isinstance(agent, ReviewedCodingAgent):
        return agent
    base = getattr(agent, "base", None)
    return base if isinstance(base, ReviewedCodingAgent) else None


@app.get(
    "/api/v1/integrations",
    summary="Every external dependency, its wiring, and a masked credential fingerprint",
)
def integrations(service: Service) -> dict[str, Any]:
    """Configuration as the running process actually sees it.

    Secrets are fingerprinted (first and last four characters) so a reviewer can
    tell *which* key is loaded without the console ever holding the key itself.
    """
    settings = get_settings()
    crosswalk = service.terminology
    sources = crosswalk.sources() if crosswalk else []
    loinc = crosswalk.loinc_table if crosswalk else None
    curated = _curated_agent(service.coding_agent)
    return {
        "app": {
            "env": settings.app_env,
            "version": app.version,
            "database_path": str(settings.database_path),
            "replay_data_path": str(settings.replay_data_path),
        },
        "gemini": {
            "configured": settings.gemini_enabled,
            "key_fingerprint": _mask_secret(settings.gemini_api_key),
            "key_env": "GEMINI_API_KEY",
            "model": settings.gemini_model,
            "fallback_model": _effective_fallback(settings),
            "api_base": settings.gemini_api_base,
            "assist_mode": settings.gemini_assist_mode.value,
            "assist_below_confidence": settings.gemini_assist_below_confidence,
            "confidence_ceiling": settings.gemini_confidence_ceiling,
            "timeout_seconds": settings.gemini_timeout_seconds,
            "max_retries": settings.gemini_max_retries,
            "max_output_tokens": settings.gemini_max_output_tokens,
            "thinking_budget": settings.gemini_thinking_budget,
        },
        "umls": {
            "configured": settings.umls_enabled,
            "key_fingerprint": _mask_secret(settings.umls_api_key),
            "key_env": "UMLS_API_KEY",
            "auth_scheme": "apiKey query parameter (not OAuth2 client credentials)",
            "client_id": settings.umls_client_id.strip() or None,
            "client_secret_fingerprint": _mask_secret(settings.umls_client_secret),
            "api_base": settings.umls_api_base,
            "vocabularies": settings.umls_vocabulary_list,
            "timeout_seconds": settings.umls_timeout_seconds,
            "max_retries": settings.umls_max_retries,
            "active": "umls" in sources,
        },
        "loinc_table": {
            "path": str(settings.loinc_table_path),
            "available": bool(loinc and loinc.available),
            "active": "loinc-table" in sources,
        },
        "fhir": {
            "base_url": settings.fhir_base_url,
            "write_enabled": settings.fhir_write_enabled,
            "write_mode": "enabled" if settings.fhir_write_enabled else "dry-run",
            "timeout_seconds": settings.fhir_timeout_seconds,
            "observation_profile": OAH_OBSERVATION_PROFILE,
            "health_measure_profile": OAH_HEALTH_MEASURE_PROFILE,
            "location_profile": OAH_LOCATION_PROFILE,
        },
        "connectors": {
            "path": str(settings.connectors_path),
            "hubeau": {
                "enabled": settings.hubeau_enabled,
                "api_base": settings.hubeau_api_base,
                "auth": "keyless",
                "timeout_seconds": settings.hubeau_timeout_seconds,
                "max_retries": settings.hubeau_max_retries,
                "parameters": HUBEAU_PARAMETERS,
            },
            "sentinel2": {
                "enabled": settings.sentinel2_enabled,
                "catalogue_base": settings.cdse_catalogue_base,
                "statistics_url": settings.cdse_statistics_url,
                "token_url": settings.cdse_token_url,
                "client_id": settings.cdse_client_id.strip() or None,
                "client_secret_fingerprint": _mask_secret(settings.cdse_client_secret),
                "credentialed": settings.cdse_enabled,
                "timeout_seconds": settings.cdse_timeout_seconds,
                "max_retries": settings.cdse_max_retries,
            },
            "status": [item.model_dump(mode="json") for item in service.connector_statuses()],
        },
        "webhook": {
            "header": "X-AquaFHIR-Secret",
            "secret_fingerprint": _mask_secret(settings.webhook_shared_secret),
            "using_default_secret": settings.webhook_shared_secret
            in {"local-demo-secret", "change-me-before-deployment"},
            "endpoint": "/api/v1/webhooks/fhir",
        },
        "policy": {
            "id": service.thresholds.policy_id,
            "status": service.thresholds.status,
            "path": str(settings.thresholds_path),
            "rules": service.thresholds.rules,
        },
        "coding": {
            "system": curated.system if curated else None,
            "path": str(settings.coding_rules_path),
            "review_confidence_threshold": settings.review_confidence_threshold,
            "codes": len(curated.rules) if curated else 0,
        },
    }


@app.get(
    "/api/v1/coding/catalog",
    summary="The curated OAH catalog a reviewer may choose from when overriding a coding",
)
def coding_catalog(service: Service) -> dict[str, Any]:
    curated = _curated_agent(service.coding_agent)
    if curated is None:
        return {"system": None, "codes": []}
    return {
        "system": curated.system,
        "codes": [
            {
                "code": rule["code"],
                "display": rule["display"],
                "aliases": list(rule.get("aliases", [])),
                "accepted_units": list(rule.get("accepted_units", [])),
                "unit_conversions": rule.get("unit_conversions", {}),
                "plausible_range": rule.get("plausible_range"),
                "leg": curated.leg_for_rule(rule).value,
                "value_set": [
                    item.model_dump() for item in curated.accepted_values_for_rule(rule)
                ],
            }
            for rule in curated.rules
        ],
    }


# -- live connectors -------------------------------------------------------


@app.get(
    "/api/v1/connectors",
    response_model=list[ConnectorStatus],
    summary="Live data connectors: what each one can do right now, and with which credentials",
)
def connectors(service: Service) -> list[ConnectorStatus]:
    return service.connector_statuses()


@app.post(
    "/api/v1/connectors/hubeau/pull",
    response_model=ConnectorPullResult,
    status_code=status.HTTP_201_CREATED,
    summary="Pull real river-quality analyses from Hub'Eau (keyless) as pending proposals",
)
def pull_hubeau(
    service: Service, request_body: ConnectorPullRequest | None = None
) -> ConnectorPullResult:
    return service.pull_hubeau(request_body or ConnectorPullRequest())


@app.get(
    "/api/v1/connectors/sentinel2/scenes",
    summary="Which Sentinel-2 L2A scenes cover a configured site (Copernicus catalogue, keyless)",
)
def sentinel_scenes(
    service: Service,
    site_code: Annotated[str, Query(description="A site_code from config/connectors.yaml")],
    days: Annotated[int, Query(ge=1, le=3660)] = 60,
    max_cloud: Annotated[float, Query(ge=0, le=100)] = 40.0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    try:
        site, scenes, url = service.sentinel_scenes(
            site_code, days=days, max_cloud=max_cloud, limit=limit
        )
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "site": site,
        "scenes": [SceneCandidate.model_dump(item, mode="json") for item in scenes],
        "request_url": url,
    }


@app.post(
    "/api/v1/connectors/sentinel2/pull",
    response_model=ConnectorPullResult,
    status_code=status.HTTP_201_CREATED,
    summary="Compute Sentinel-2 NDCI over a configured site (needs a CDSE OAuth client)",
)
def pull_sentinel2(request_body: ConnectorPullRequest, service: Service) -> ConnectorPullResult:
    try:
        return service.pull_sentinel2(request_body)
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


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
    "/api/v1/replay/run",
    response_model=IncidentRunReport,
    status_code=status.HTTP_201_CREATED,
    summary="Load a fixture and drive it through the whole round under a named reviewer",
)
def run_replay_dataset(
    service: Service,
    reviewer: Annotated[str, Query(min_length=1, max_length=120)],
    dataset: Annotated[str | None, Query(pattern=r"^(oder-replay|incidents)$")] = None,
) -> IncidentRunReport:
    try:
        return service.run_replay(dataset, reviewer)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post(
    "/api/v1/replay",
    response_model=list[MappingProposal],
    status_code=status.HTTP_201_CREATED,
    summary="Load a fixture as pending proposals (the synthetic Oder timeline by default)",
)
def replay_dataset(
    service: Service,
    dataset: Annotated[
        str | None,
        Query(
            pattern=r"^(oder-replay|incidents)$",
            description="`incidents` loads data/incidents.csv; omitted = the Oder replay",
        ),
    ] = None,
) -> list[MappingProposal]:
    try:
        return service.replay(dataset=dataset)
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


@app.get(
    "/api/v1/proposals/{proposal_id}/taxon-suggestions",
    response_model=list[TerminologyMatch],
    summary="Suggest a GBIF Backbone taxon for the organism named in the source label",
)
def taxon_suggestions(proposal_id: str, service: Service) -> list[TerminologyMatch]:
    try:
        return service.suggest_taxa(proposal_id)
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail="Proposal not found") from error


@app.get(
    "/api/v1/proposals/{proposal_id}/normalization",
    response_model=NormalizationPreview,
    summary="What approving this proposal under a given catalog code would produce",
)
def normalization_preview(
    proposal_id: str,
    service: Service,
    code: Annotated[str, Query(description="A code from the curated OAH catalog")],
) -> NormalizationPreview:
    try:
        return service.normalization_preview(proposal_id, code)
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail="Proposal not found") from error


@app.post(
    "/api/v1/proposals/{proposal_id}/unit-suggestion",
    response_model=UnitSuggestionResult,
    summary="Suggest an unresolved unit conversion for explicit expert review",
)
def suggest_unit_conversion(
    proposal_id: str, service: Service,
    code: Annotated[str, Query(description="A code from the curated OAH catalog")],
) -> UnitSuggestionResult:
    try:
        return service.suggest_unit_conversion(proposal_id, code)
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail="Proposal not found") from error
    except InvalidReviewStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get(
    "/api/v1/proposals/{proposal_id}/observation",
    summary="The stored Observation and the receipt from the approval that built it",
)
def published_observation(proposal_id: str, service: Service) -> dict[str, Any]:
    try:
        stored = service.published_observation(proposal_id)
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail="Proposal not found") from error
    if stored is None:
        raise HTTPException(
            status_code=404, detail="This proposal has no published Observation"
        )
    return stored


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


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Browsers request this path unprompted, whatever the page links to."""
    return FileResponse(STATIC_DIR / "brand" / "favicon.ico", media_type="image/x-icon")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def run() -> None:
    settings = get_settings()
    uvicorn.run("aquafhir.main:app", host=settings.app_host, port=settings.app_port, reload=False)
