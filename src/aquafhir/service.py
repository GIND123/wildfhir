import csv
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aquafhir.briefing import KNOWN_AUDIENCES, BriefingWriter
from aquafhir.coding import CodingProposer, range_violation
from aquafhir.config import AssistMode
from aquafhir.connectors import (
    HUBEAU_PARAMETERS,
    ConnectorUnavailableError,
    CopernicusClient,
    HubEauClient,
)
from aquafhir.fhir import (
    OAH_LOCATION_PROFILE,
    FhirClient,
    build_resources,
    profile_for,
    transaction_bundle,
)
from aquafhir.gemini import GeminiClient, GeminiError
from aquafhir.intake import UnstructuredIntake
from aquafhir.models import (
    Alert,
    AlertBriefing,
    ApprovalResult,
    BatchApprovalResult,
    BatchReviewDecision,
    Coding,
    ConnectorPullRequest,
    ConnectorPullResult,
    ConnectorStatus,
    IntakeRequest,
    IntakeResult,
    MappingProposal,
    NormalizationPreview,
    OneHealthLeg,
    RawReading,
    RejectDecision,
    ReviewDecision,
    ReviewStatus,
    SceneCandidate,
    SituationReport,
    TerminologyMatch,
    UnitSuggestionResult,
)
from aquafhir.repository import Repository
from aquafhir.terminology import TerminologyCrosswalk
from aquafhir.thresholds import ThresholdPolicy
from aquafhir.unit_assist import suggest_unit

logger = logging.getLogger(__name__)


class ProposalNotFoundError(LookupError):
    pass


class AlertNotFoundError(LookupError):
    pass


class InvalidReviewStateError(ValueError):
    pass


class ApprovalValidationError(ValueError):
    """The reviewer's decision cannot be published as stated.

    Distinct from `InvalidReviewStateError`, which is about *when* a decision
    may be made. This is about *what* was decided: an unknown code, a unit the
    selected rule does not accept, or a value outside its plausible range.
    Nothing is published and no alert is raised.
    """


class AiUnavailableError(RuntimeError):
    """Raised when an AI-only endpoint is called without a working Gemini key."""


@dataclass(frozen=True)
class ResolvedDecision:
    """Exactly what will be published: decided by the server, not the client."""

    coding: Coding
    leg: OneHealthLeg
    value: float | None
    unit: str | None
    value_coding: Coding | None
    correction_reason: str | None


class BridgeService:
    def __init__(
        self,
        repository: Repository,
        coding_agent: CodingProposer,
        thresholds: ThresholdPolicy,
        fhir_client: FhirClient,
        intake: UnstructuredIntake | None = None,
        briefing_writer: BriefingWriter | None = None,
        terminology: TerminologyCrosswalk | None = None,
        replay_path: Path | None = None,
        gemini: "GeminiClient | None" = None,
        hubeau: HubEauClient | None = None,
        copernicus: CopernicusClient | None = None,
        connector_config: dict[str, Any] | None = None,
    ) -> None:
        self.repository = repository
        self.coding_agent = coding_agent
        self.thresholds = thresholds
        self.fhir_client = fhir_client
        self.intake = intake
        self.briefing_writer = briefing_writer
        self.terminology = terminology
        self.replay_path = replay_path
        # Held only so status reporting can read the outcome of the last real
        # call. Nothing in the pipeline reaches the model through this handle.
        self.gemini = gemini
        self.hubeau = hubeau
        self.copernicus = copernicus
        self.connector_config = connector_config or {
            "hubeau": {"stations": []},
            "sentinel2": {"sites": []},
        }

    # -- ingestion ---------------------------------------------------------

    def propose(self, reading: RawReading) -> MappingProposal:
        proposal = self.coding_agent.propose(reading)
        # Flagged, never merged. Replaying a dataset intentionally produces
        # duplicates, so this warns the reviewer rather than blocking ingestion.
        proposal.duplicate_of = self.repository.find_duplicate(proposal)
        if proposal.duplicate_of:
            proposal.rationale = (
                f"{proposal.rationale} An identical reading was already ingested "
                f"as {proposal.duplicate_of}."
            ).strip()
        self.repository.save_proposal(proposal)
        self.repository.append_provenance(
            "mapping-proposed", proposal.id, proposal.model_dump(mode="json")
        )
        self._chain_ai_call(proposal.id, proposal.ai_audit)
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
        try:
            readings, warnings, attribution, audit = self.intake.extract(request)
        except GeminiError as error:
            # A failed extraction still has to leave a trace, attributed to the
            # intake itself rather than to a proposal it never produced.
            self._chain_ai_call("unstructured-intake", error.audit)
            raise
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
        # Chained against the intake, not against the first reading it yielded.
        self._chain_ai_call(
            attribution.prompt_hash if attribution else "unstructured-intake", audit
        )
        return IntakeResult(
            proposals=proposals,
            warnings=warnings,
            extracted_count=len(readings),
            rejected_count=max(0, len(warnings) - len(readings)),
            ai=attribution,
            ai_audit=audit,
        )

    # -- live connectors ---------------------------------------------------

    def connector_statuses(self) -> list[ConnectorStatus]:
        hubeau_cfg = self.connector_config.get("hubeau", {})
        sentinel_cfg = self.connector_config.get("sentinel2", {})
        statuses: list[ConnectorStatus] = []
        hub = self.hubeau
        statuses.append(
            ConnectorStatus(
                name="hubeau",
                provider="Hub'Eau (eaufrance.fr) river water quality, Naiades",
                enabled=bool(hub and hub.enabled),
                auth="keyless",
                live=bool(hub and hub.enabled),
                detail=(
                    "Real laboratory analyses from named French monitoring stations, including "
                    "the Garonne inside Toulouse, a OneAquaHealth pilot city. Keyless. Labels and "
                    "units arrive in French exactly as the laboratory reported them; the reviewed "
                    "catalog decides what can be published."
                    if hub and hub.enabled
                    else "Disabled (HUBEAU_ENABLED=false)."
                ),
                api_base=hub.api_base if hub else "",
                sites=list(hubeau_cfg.get("stations", [])),
            )
        )
        cds = self.copernicus
        if cds is None or not cds.enabled:
            auth, live = "credentials-required", False
            detail = "Disabled (SENTINEL2_ENABLED=false)."
        elif cds.credentialed:
            auth, live = "credentials-configured", True
            detail = (
                "Copernicus Data Space Ecosystem. Scene listing from the product catalogue is "
                "keyless; NDCI over a site is computed by the Sentinel Hub Statistical API with "
                "the configured OAuth client. Every reading cites the catalogue scene it came from."
            )
        else:
            auth, live = "credentials-required", True
            detail = (
                "Copernicus Data Space Ecosystem. Scene listing (which Sentinel-2 L2A products "
                "cover a site, when, how cloudy) works keyless right now. Computing NDCI over a "
                "site needs CDSE_CLIENT_ID and CDSE_CLIENT_SECRET, which are not set."
            )
        statuses.append(
            ConnectorStatus(
                name="sentinel2",
                provider="Copernicus Data Space Ecosystem, Sentinel-2 L2A",
                enabled=bool(cds and cds.enabled),
                auth=auth,
                live=live,
                detail=detail,
                api_base=cds.api_base if cds else "",
                sites=list(sentinel_cfg.get("sites", [])),
            )
        )
        return statuses

    def pull_hubeau(self, request: ConnectorPullRequest) -> ConnectorPullResult:
        """Fetch real readings from Hub'Eau and queue them as pending proposals."""
        if self.hubeau is None or not self.hubeau.enabled:
            raise ConnectorUnavailableError("Hub'Eau connector is disabled (HUBEAU_ENABLED=false)")
        hubeau_cfg = self.connector_config.get("hubeau", {})
        configured = {str(item["code"]): item for item in hubeau_cfg.get("stations", [])}
        unknown = [code for code in request.stations if code not in configured]
        if unknown:
            raise ConnectorUnavailableError(
                f"Station(s) {', '.join(unknown)} are not in config/connectors.yaml; "
                "only configured stations can be pulled"
            )
        wanted = list(request.stations) or list(configured)
        if not wanted:
            raise ConnectorUnavailableError(
                "No Hub'Eau station is configured in config/connectors.yaml"
            )
        parameters = list(hubeau_cfg.get("parameters") or HUBEAU_PARAMETERS)
        parameters = [str(code) for code in parameters if str(code) in HUBEAU_PARAMETERS]
        since = datetime.now(UTC) - timedelta(days=request.days)
        rows, url = self.hubeau.fetch_analyses(wanted, parameters, since, request.limit)
        readings, skipped = self.hubeau.to_readings(rows, configured)
        proposals = [self.propose(reading) for reading in readings]
        result = ConnectorPullResult(
            connector="hubeau",
            source_id=self.hubeau.source_id,
            fetched=len(rows),
            skipped=skipped,
            proposals=proposals,
            request_hash=_sha256(url),
            request_url=url,
        )
        self._chain_pull(
            result,
            {"stations": wanted, "parameters": parameters, "since": since.date().isoformat()},
        )
        return result

    def sentinel_scenes(
        self, site_code: str, *, days: int = 60, max_cloud: float = 40.0, limit: int = 10
    ) -> tuple[dict[str, Any], list[SceneCandidate], str]:
        """Which Sentinel-2 scenes cover a configured site. Read-only, keyless."""
        self._require_sentinel()
        site = self._sentinel_site(site_code)
        scenes, url = self.copernicus.scenes(
            float(site["latitude"]),
            float(site["longitude"]),
            days=days,
            max_cloud=max_cloud,
            limit=limit,
        )
        return site, scenes, url

    def pull_sentinel2(self, request: ConnectorPullRequest) -> ConnectorPullResult:
        """Compute NDCI over a configured site and queue one proposal per clear day."""
        self._require_sentinel()
        if not request.site_code:
            raise ConnectorUnavailableError(
                "Sentinel-2 pull needs a site_code from config/connectors.yaml"
            )
        site, scenes, scenes_url = self.sentinel_scenes(
            request.site_code, days=request.days, max_cloud=request.max_cloud, limit=100
        )
        intervals, request_hash, statistics_url = self.copernicus.ndci(
            [float(item) for item in site["bbox"]], days=request.days, max_cloud=request.max_cloud
        )
        readings = self.copernicus.to_readings(
            intervals[: request.limit], site, scenes, request_hash
        )
        proposals = [self.propose(reading) for reading in readings]
        result = ConnectorPullResult(
            connector="sentinel2",
            source_id=self.copernicus.source_id,
            fetched=len(intervals),
            skipped=[],
            proposals=proposals,
            request_hash=request_hash,
            request_url=statistics_url,
        )
        self._chain_pull(
            result,
            {"site_code": site["site_code"], "days": request.days, "max_cloud": request.max_cloud,
             "scenes_url_hash": _sha256(scenes_url), "scenes": len(scenes)},
        )
        return result

    def _require_sentinel(self) -> None:
        if self.copernicus is None or not self.copernicus.enabled:
            raise ConnectorUnavailableError(
                "Sentinel-2 connector is disabled (SENTINEL2_ENABLED=false)"
            )

    def _sentinel_site(self, site_code: str) -> dict[str, Any]:
        for site in self.connector_config.get("sentinel2", {}).get("sites", []):
            if site.get("site_code") == site_code:
                return site
        raise ProposalNotFoundError(f"No Sentinel-2 site {site_code!r} in config/connectors.yaml")

    def _chain_pull(self, result: ConnectorPullResult, query: dict[str, Any]) -> None:
        """One chain entry per pull: which query, how many rows, which proposals.

        The request URL is hashed, not stored: it is reproducible from the
        query fields and the chain should not accumulate long strings.
        """
        self.repository.append_provenance(
            "connector-pull",
            result.request_hash,
            {
                "connector": result.connector,
                "source_id": result.source_id,
                "query": query,
                "fetched": result.fetched,
                "skipped": len(result.skipped),
                "queued": len(result.proposals),
                "proposal_ids": [item.id for item in result.proposals],
                "fetched_at": result.fetched_at.isoformat(),
            },
        )

    # -- review-time validation --------------------------------------------

    @property
    def catalog(self):
        """The reviewed rules, reachable whether or not a model wrapped the proposer."""
        return self.coding_agent.catalog

    def normalization_preview(self, proposal_id: str, code: str) -> NormalizationPreview:
        """What approving this proposal under `code` would publish.

        The dialog shows this; it never sends the numbers back. Approval runs
        the same arithmetic again, so what a reviewer sees and what is
        published cannot drift apart.
        """
        proposal = self.repository.get_proposal(proposal_id)
        if not proposal:
            raise ProposalNotFoundError(proposal_id)
        rule = self.catalog.rule_for_code(code)
        if not rule:
            raise ApprovalValidationError(
                f"{code!r} is not a code in the curated catalog"
            )
        reading = proposal.reading
        accepted = self.catalog.accepted_units_for_rule(rule)
        limits = rule.get("plausible_range")
        common = {
            "code": rule["code"],
            "display": rule["display"],
            "system": self.catalog.system,
            "leg": self.catalog.leg_for_rule(rule),
            "value_kind": "coded" if reading.is_coded else "quantity",
            "source_value": reading.value,
            "source_unit": reading.unit,
            "source_coded_value": reading.coded_value,
            "accepted_units": accepted,
            "accepted_values": self.catalog.accepted_values_for_rule(rule),
            "interpreted_unit": self.catalog.canonical_unit(reading.unit, rule),
            "ai_result": proposal.unit_suggestions.get(code),
            "ai_available": self.unit_assist_available,
            "plausible_range": (
                {"min": float(limits["min"]), "max": float(limits["max"])} if limits else None
            ),
        }
        if reading.is_coded:
            value_coding, note = self.catalog.normalize_coded(reading.coded_value or "", rule)
            if value_coding is None:
                status = (
                    "kind-mismatch"
                    if not self.catalog.takes_coded_value(rule)
                    else "value-unresolved"
                )
                return NormalizationPreview(**common, status=status, message=note.strip())
            return NormalizationPreview(
                **common,
                status="ok",
                normalized_coding=value_coding,
                formula=f"'{reading.coded_value}' → {value_coding.code} ({value_coding.display})",
                message=note.strip(),
            )

        value, unit, note = self.catalog.normalize_unit(
            reading.value if reading.value is not None else 0.0, reading.unit, rule
        )
        if unit is None:
            if not self.catalog.takes_quantity(rule):
                status = "kind-mismatch"
            else:
                status = "out-of-range" if "plausible range" in note else "unit-unresolved"
            return NormalizationPreview(**common, status=status, message=note.strip())

        interpreted = self.catalog.canonical_unit(reading.unit, rule)
        conversion = rule.get("unit_conversions", {}).get(interpreted)
        factor = float(conversion["factor"]) if conversion else 1.0
        formula = (
            f"{_trim(reading.value)} {reading.unit} × {_trim(factor)} = {_trim(value)} {unit}"
            if conversion
            else f"{_trim(value)} {unit} (already an accepted UCUM unit)"
        )
        return NormalizationPreview(
            **common,
            status="ok",
            normalized_value=value,
            normalized_unit=unit,
            factor=factor,
            formula=formula,
            message=note.strip(),
            conversion_origin=(
                "reviewed-alias" if interpreted != reading.unit else "reviewed-catalog"
            ),
        )

    @property
    def unit_assist_available(self) -> bool:
        mode = getattr(self.coding_agent, "assist_mode", AssistMode.AUTO)
        return bool(self.gemini and self.gemini.enabled and mode != AssistMode.OFF)

    def suggest_unit_conversion(self, proposal_id: str, code: str) -> UnitSuggestionResult:
        proposal = self._pending_proposal(proposal_id)
        preview = self.normalization_preview(proposal_id, code)
        if preview.status != "unit-unresolved":
            raise ApprovalValidationError("AI unit suggestions require an unresolved source unit")
        existing = proposal.unit_suggestions.get(code)
        if existing and existing.status != "unavailable":
            return existing
        if not self.unit_assist_available:
            return UnitSuggestionResult(
                status="unavailable", message="Gemini unit assist is disabled."
            )
        rule = self.catalog.rule_for_code(code)
        assert rule is not None and self.gemini is not None
        try:
            result, audit = suggest_unit(self.gemini, self.catalog, proposal.reading, rule)
        except GeminiError as error:
            self._chain_ai_call(proposal_id, error.audit)
            return UnitSuggestionResult(
                status="unavailable",
                message="Gemini gave no usable suggestion. Retry or enter a correction.",
            )
        self._chain_ai_call(proposal_id, audit)
        stored = self.repository.save_unit_suggestion(proposal_id, code, result)
        if stored is None:
            raise InvalidReviewStateError("Proposal was decided while Gemini was responding")
        if stored == result:
            self.repository.append_provenance(
                "unit-suggestion", proposal_id, {"code": code, **result.model_dump(mode="json")}
            )
        return stored

    def _resolve_decision(
        self, proposal: MappingProposal, decision: ReviewDecision
    ) -> ResolvedDecision:
        """Decide the exact coding and value to publish. The client cannot.

        This is the review gate's teeth. Before it existed, a reviewer could
        approve `2444 uS/cm` as `2319 mS/cm`: the override path assigned
        whatever the client sent, so neither the accepted-unit list nor the
        plausible range was consulted and a false high-severity incident
        followed. A coded value is held to the same standard: only a concept
        from the rule's reviewed value set can be published.
        """
        selected = (decision.coding.code if decision.coding else None) or (
            proposal.coding.code if proposal.coding else None
        )
        if not selected:
            raise InvalidReviewStateError(
                "Select a code from the curated catalog before approving"
            )
        rule = self.catalog.rule_for_code(selected)
        if not rule:
            raise ApprovalValidationError(
                f"{selected!r} is not a code in the curated catalog"
            )
        # Canonical every time: the system and display come from the reviewed
        # catalog, never from the request body.
        coding = self.catalog.coding_for_code(rule["code"])
        assert coding is not None
        leg = self.catalog.leg_for_rule(rule)
        reading = proposal.reading
        changed_code = not proposal.coding or proposal.coding.code != rule["code"]

        if decision.unit_suggestion_id:
            result = proposal.unit_suggestions.get(selected)
            suggestion = result.suggestion if result else None
            if not suggestion or suggestion.id != decision.unit_suggestion_id:
                raise ApprovalValidationError(
                    "Unit suggestion does not belong to this proposal and code"
                )

        # -- coded indicator -------------------------------------------------
        if reading.is_coded or decision.coded_value:
            if decision.normalized_value is not None:
                raise ApprovalValidationError(
                    "This reading carries a coded value; correct it with coded_value, "
                    "not a quantity"
                )
            if decision.coded_value:
                word = decision.coded_value
                reason = (decision.correction_reason or "").strip()
            elif not changed_code and proposal.normalized_coding is not None:
                return ResolvedDecision(coding, leg, None, None, proposal.normalized_coding, None)
            else:
                word = reading.coded_value or ""
                reason = ""
            value_coding, note = self.catalog.normalize_coded(word, rule)
            if value_coding is None:
                raise ApprovalValidationError(
                    f"{note.strip()} Supply an expert correction (coded_value plus a reason) "
                    "choosing one of the reviewed values."
                )
            return ResolvedDecision(coding, leg, None, None, value_coding, reason or None)

        # -- quantity indicator ----------------------------------------------
        accepted = self.catalog.accepted_units_for_rule(rule)
        if decision.normalized_value is not None:
            value = decision.normalized_value
            unit = decision.normalized_unit or ""
            reason = (decision.correction_reason or "").strip()
        else:
            derived, derived_unit, note = self.catalog.normalize_unit(
                reading.value if reading.value is not None else 0.0, reading.unit, rule
            )
            if derived is None or not derived_unit:
                raise ApprovalValidationError(
                    f"{note.strip()} Supply an expert correction with a reason "
                    "if the source value itself needs replacing."
                )
            value, unit = derived, derived_unit
            reason = ""

        if unit not in accepted:
            raise ApprovalValidationError(
                f"{unit!r} is not an accepted unit for {rule['code']!r}. "
                f"Accepted: {', '.join(accepted) or 'none (coded value only)'}"
            )
        violation = range_violation(value, unit, rule)
        if violation:
            raise ApprovalValidationError(violation)
        return ResolvedDecision(coding, leg, value, unit, None, reason or None)

    def approve(self, proposal_id: str, decision: ReviewDecision) -> ApprovalResult:
        proposal = self._pending_proposal(proposal_id)
        resolved = self._resolve_decision(proposal, decision)
        proposal.coding = resolved.coding
        proposal.leg = resolved.leg
        proposal.normalized_value = resolved.value
        proposal.normalized_unit = resolved.unit
        proposal.normalized_coding = resolved.value_coding
        proposal.correction_reason = resolved.correction_reason
        if decision.secondary_coding:
            proposal.secondary_coding = decision.secondary_coding
        if decision.taxon:
            proposal.taxon = decision.taxon

        location, organization, observation = build_resources(proposal)
        profile = profile_for(proposal)
        validation = {
            "location": self.fhir_client.validate(location, OAH_LOCATION_PROFILE),
            "observation": self.fhir_client.validate(observation, profile),
        }
        publication = self.fhir_client.publish(
            transaction_bundle((location, organization, observation))
        )
        fhir_response = {"validation": validation, "transaction": publication}

        proposal.status = ReviewStatus.APPROVED
        proposal.reviewer = decision.reviewer
        proposal.reviewed_at = datetime.now(UTC)
        self.repository.save_proposal(proposal)
        self.repository.save_observation(proposal.id, observation, fhir_response)
        self.repository.append_provenance(
            "mapping-approved",
            proposal.id,
            {
                "reviewer": decision.reviewer,
                "observation_id": observation["id"],
                "observation_hash": _digest(observation),
                "profile": profile,
                "one_health_leg": proposal.leg.value,
                "proposer": proposal.proposer.value,
        "ai_accepted": proposal.ai is not None or decision.unit_suggestion_id is not None,
                "ai_prompt_hash": proposal.ai.prompt_hash if proposal.ai else None,
                # The exact published facts, not a boolean saying something
                # happened. An auditor should not have to re-derive what was
                # approved from the Observation.
                "published_coding": proposal.coding.model_dump() if proposal.coding else None,
                "published_value": proposal.normalized_value,
                "published_unit": proposal.normalized_unit,
                "published_value_coding": (
                    proposal.normalized_coding.model_dump() if proposal.normalized_coding else None
                ),
                "reviewer_overrode_coding": decision.coding is not None,
                "expert_correction": resolved.correction_reason is not None,
                "correction_reason": resolved.correction_reason,
                "unit_suggestion_id": decision.unit_suggestion_id,
                "unit_suggestion": (
                    proposal.unit_suggestions[resolved.coding.code].model_dump(mode="json")
                    if decision.unit_suggestion_id
                    else None
                ),
                "secondary_coding": (
                    proposal.secondary_coding.model_dump()
                    if proposal.secondary_coding
                    else None
                ),
                "taxon": proposal.taxon.model_dump() if proposal.taxon else None,
                "duplicate_of": proposal.duplicate_of,
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

    def _chain_ai_call(self, entity_id: str, record: dict[str, Any] | None) -> None:
        """Append one AI call to the chain, against the entity it belongs to.

        The record is passed in rather than pulled from the client. A shared
        queue on the client looked simpler but was wrong twice over: two
        concurrent requests would drain each other's records, and an intake
        call was attributed to the first proposal it produced, because
        `propose()` drained the queue before `ingest_unstructured()` could.

        Failures matter here more than successes. A quota-exhausted bridge
        still produces proposals via the rules fallback, and without this the
        chain would show a clean run with no trace that the model was tried
        and refused. Records carry hashes and categories only: no prompt text,
        no provider error body, no key.
        """
        if record:
            self.repository.append_provenance("ai-call", entity_id, record)

    def published_observation(self, proposal_id: str) -> dict[str, Any] | None:
        """The stored Observation and receipt for an approved proposal."""
        if not self.repository.get_proposal(proposal_id):
            raise ProposalNotFoundError(proposal_id)
        return self.repository.get_observation_for_proposal(proposal_id)

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

        try:
            briefing = self.briefing_writer.draft(
                alert=alert,
                audience=audience,
                policy_id=self.thresholds.policy_id,
                policy_status=self.thresholds.status,
                observation=observation,
                site_history=history,
            )
        except GeminiError as error:
            self._chain_ai_call(alert.id, error.audit)
            raise
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
        self._chain_ai_call(briefing.id, briefing.ai_audit)
        return briefing

    def situation_report(self, limit: int = 100) -> SituationReport:
        if self.briefing_writer is None or not self.briefing_writer.available:
            raise AiUnavailableError("Situation reports need GEMINI_API_KEY")
        observations = self.repository.observation_summaries(limit=limit)
        alerts = [alert.model_dump(mode="json") for alert in self.repository.list_alerts(limit)]
        pending = self.repository.count_proposals_by_status().get(ReviewStatus.PENDING.value, 0)

        try:
            report = self.briefing_writer.situation_report(
                observations=observations,
                alerts=alerts,
                pending_count=pending,
                policy_id=self.thresholds.policy_id,
                policy_status=self.thresholds.status,
            )
        except GeminiError as error:
            self._chain_ai_call("situation-report", error.audit)
            raise
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
        self._chain_ai_call(
            report.ai.response_hash if report.ai else "situation-report", report.ai_audit
        )
        return report

    # -- terminology crosswalk ----------------------------------------------

    def suggest_terminology(self, proposal_id: str) -> list[TerminologyMatch]:
        """Suggest a real LOINC/SNOMED CT code for a proposal's OAH coding.

        Read-only. Nothing here is attached to the proposal until a reviewer
        supplies `ReviewDecision.secondary_coding` at approval time.
        """
        if self.terminology is None or not self.terminology.available:
            raise AiUnavailableError(
                "Terminology crosswalk has no source: the LOINC table is missing and "
                "UMLS_API_KEY is unset. Approve using the curated OAH code alone instead"
            )
        proposal = self.repository.get_proposal(proposal_id)
        if not proposal:
            raise ProposalNotFoundError(proposal_id)
        if not proposal.coding:
            return []
        return self.terminology.suggest(proposal.coding.display)

    def suggest_taxa(self, proposal_id: str) -> list[TerminologyMatch]:
        """Suggest a GBIF taxon for the organism named in the source label.

        Unlike `suggest_terminology`, this does not need a curated coding. An
        organism name most often survives in readings the catalog could not
        code at all, and refusing to look would lose exactly the cases where
        the identification matters most.
        """
        if self.terminology is None or not self.terminology.taxa_available:
            raise AiUnavailableError(
                "Biodiversity crosswalk is disabled (GBIF_ENABLED=false)"
            )
        proposal = self.repository.get_proposal(proposal_id)
        if not proposal:
            raise ProposalNotFoundError(proposal_id)
        return self.terminology.suggest_taxa(proposal.reading.parameter)

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


def reading_from_csv_row(row: dict[str, str], raw_payload: dict[str, Any]) -> RawReading:
    """Build a reading from one fixture row.

    A row carries either `value` + `unit` or a `coded_value`; an empty `value`
    cell with a `coded_value` is how the citizen-science fixtures express
    "foam: present" without inventing a number for it.
    """
    evidence = (row.get("evidence_url") or "").strip()
    coded = (row.get("coded_value") or "").strip()
    raw_value = (row.get("value") or "").strip()
    return RawReading(
        source_id=row["source_id"],
        source_type=row["source_type"],
        parameter=row["parameter"],
        value=float(raw_value) if raw_value else None,
        unit=(row.get("unit") or "").strip(),
        coded_value=coded or None,
        observed_at=row["observed_at"],
        site_code=row["site_code"],
        site_name=row["site_name"],
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        evidence_url=evidence or None,
        raw_payload=raw_payload,
    )


def _reading_from_csv_row(row: dict[str, str]) -> RawReading:
    return reading_from_csv_row(
        row, {"replay_source": "data/oder-replay.csv", "synthetic": True}
    )


__all__ = [
    "AiUnavailableError",
    "AlertNotFoundError",
    "ApprovalValidationError",
    "BridgeService",
    "ConnectorUnavailableError",
    "GeminiError",
    "InvalidReviewStateError",
    "ProposalNotFoundError",
    "reading_from_csv_row",
]


def _digest(document: dict[str, Any]) -> str:
    """SHA-256 of the exact resource published, so the chain pins the payload."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _trim(value: float | None) -> str:
    """Render a number the way a reviewer would write it, not as a float repr."""
    if value is None:
        return "-"
    text = f"{value:.10g}"
    return text
