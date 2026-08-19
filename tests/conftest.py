from pathlib import Path

import pytest

from aquafhir.coding import ReviewedCodingAgent
from aquafhir.fhir import FhirClient
from aquafhir.repository import Repository
from aquafhir.service import BridgeService
from aquafhir.thresholds import ThresholdPolicy

ROOT = Path(__file__).parents[1]


@pytest.fixture
def service(tmp_path: Path) -> BridgeService:
    return BridgeService(
        repository=Repository(tmp_path / "test.db"),
        coding_agent=ReviewedCodingAgent(ROOT / "config" / "coding-rules.yaml"),
        thresholds=ThresholdPolicy(ROOT / "config" / "thresholds.yaml"),
        fhir_client=FhirClient("http://unused.test/fhir", write_enabled=False, timeout=1),
    )

