import re
from datetime import datetime
from typing import Any

import httpx

from aquafhir.models import MappingProposal

OAH_OBSERVATION_PROFILE = (
    "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-indicators-oah"
)
OAH_LOCATION_PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/location-oah"
OAH_LOCATION_IDENTIFIER = "https://aquafhir.example/location-id"
OAH_SOURCE_IDENTIFIER = "https://aquafhir.example/source-id"


def fhir_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9\-.]", "-", value).strip("-")
    return (normalized or "unknown")[:64]


def build_resources(
    proposal: MappingProposal,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not proposal.coding or proposal.normalized_value is None or not proposal.normalized_unit:
        raise ValueError("A coding and normalized UCUM quantity are required before approval")

    reading = proposal.reading
    location_id = fhir_id(reading.site_code)
    organization_id = fhir_id(reading.source_id)
    observation_id = fhir_id(f"obs-{proposal.id}")

    location = {
        "resourceType": "Location",
        "id": location_id,
        "meta": {"profile": [OAH_LOCATION_PROFILE]},
        "identifier": [{"system": OAH_LOCATION_IDENTIFIER, "value": reading.site_code}],
        "status": "active",
        "name": reading.site_name,
        "mode": "instance",
        "type": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "420531007",
                        "display": "River",
                    }
                ]
            }
        ],
        "position": {"longitude": reading.longitude, "latitude": reading.latitude},
    }
    organization = {
        "resourceType": "Organization",
        "id": organization_id,
        "identifier": [{"system": OAH_SOURCE_IDENTIFIER, "value": reading.source_id}],
        "active": True,
        "name": reading.source_id,
    }
    codings = [proposal.coding.model_dump()]
    if proposal.secondary_coding:
        codings.append(proposal.secondary_coding.model_dump())
    observation: dict[str, Any] = {
        "resourceType": "Observation",
        "id": observation_id,
        "meta": {
            "profile": [OAH_OBSERVATION_PROFILE],
            "tag": [
                {
                    "system": "https://aquafhir.example/source-type",
                    "code": reading.source_type.value,
                }
            ],
        },
        "identifier": [
            {"system": "https://aquafhir.example/proposal-id", "value": proposal.id}
        ],
        "status": "final",
        "code": {
            "coding": codings,
            "text": proposal.coding.display,
        },
        "subject": {"reference": f"Location/{location_id}", "display": reading.site_name},
        "effectiveDateTime": reading.observed_at.isoformat(),
        "performer": [{"reference": f"Organization/{organization_id}"}],
        "valueQuantity": {
            "value": proposal.normalized_value,
            "unit": proposal.normalized_unit,
            "system": "http://unitsofmeasure.org",
            "code": proposal.normalized_unit,
        },
        "note": [{"text": f"Mapped from '{reading.parameter}' after human review."}],
    }
    if reading.evidence_url:
        observation["note"].append(
            {"text": f"Source evidence URI: {reading.evidence_url}"}
        )
    if proposal.secondary_coding:
        observation["note"].append(
            {
                "text": (
                    f"Second coding {proposal.secondary_coding.system}|"
                    f"{proposal.secondary_coding.code} attached by reviewer "
                    "from a terminology crosswalk suggestion."
                )
            }
        )
    return location, organization, observation


def transaction_bundle(resources: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": resource,
                "request": {
                    "method": "PUT",
                    "url": f"{resource['resourceType']}/{resource['id']}",
                },
            }
            for resource in resources
        ],
    }


class FhirClient:
    def __init__(self, base_url: str, write_enabled: bool, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.write_enabled = write_enabled
        self.timeout = timeout

    def publish(self, bundle: dict[str, Any]) -> dict[str, Any]:
        if not self.write_enabled:
            return {"mode": "dry-run", "resource_count": len(bundle["entry"])}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                self.base_url,
                json=bundle,
                headers={"Accept": "application/fhir+json"},
            )
            response.raise_for_status()
            return response.json()

    def validate(self, resource: dict[str, Any], profile: str) -> dict[str, Any]:
        if not self.write_enabled:
            return {"mode": "dry-run", "profile": profile}
        resource_type = resource["resourceType"]
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/{resource_type}/$validate",
                params={"profile": profile},
                json=resource,
                headers={"Content-Type": "application/fhir+json"},
            )
            response.raise_for_status()
            outcome = response.json()
        failures = [
            issue
            for issue in outcome.get("issue", [])
            if issue.get("severity") in {"fatal", "error"}
        ]
        if failures:
            diagnostics = "; ".join(
                issue.get("diagnostics", issue.get("code", "validation error"))
                for issue in failures
            )
            raise ValueError(f"FHIR profile validation failed: {diagnostics}")
        return outcome

    def metadata(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                f"{self.base_url}/metadata",
                headers={"Accept": "application/fhir+json"},
            )
            response.raise_for_status()
            return response.json()

    def install_subscription(self, callback_url: str, shared_secret: str) -> dict[str, Any]:
        resource = {
            "resourceType": "Subscription",
            "status": "requested",
            "reason": "Forward OAH environmental observations to AquaFHIR policy evaluation",
            "criteria": "Observation?status=final",
            "channel": {
                "type": "rest-hook",
                "endpoint": callback_url,
                "header": [f"X-AquaFHIR-Secret: {shared_secret}"],
            },
        }
        if not self.write_enabled:
            return {"mode": "dry-run", "resource": resource}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/Subscription",
                json=resource,
                headers={"Content-Type": "application/fhir+json"},
            )
            response.raise_for_status()
            return response.json()

    def fetch_recent_observations(self, since: datetime) -> list[dict[str, Any]]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                f"{self.base_url}/Observation",
                params={
                    "status": "final",
                    "_lastUpdated": f"ge{since.isoformat()}",
                    "_sort": "_lastUpdated",
                    "_count": "100",
                },
                headers={"Accept": "application/fhir+json"},
            )
            response.raise_for_status()
            bundle = response.json()
        return [
            entry["resource"]
            for entry in bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "Observation"
        ]
