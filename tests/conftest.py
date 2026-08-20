from pathlib import Path

import pytest

from aquafhir.briefing import BriefingWriter
from aquafhir.coding import ReviewedCodingAgent
from aquafhir.coding_llm import GeminiCodingAgent
from aquafhir.config import AssistMode
from aquafhir.fhir import FhirClient
from aquafhir.gemini import GeminiClient
from aquafhir.intake import UnstructuredIntake
from aquafhir.repository import Repository
from aquafhir.service import BridgeService
from aquafhir.thresholds import ThresholdPolicy
from tests.fakes import FakeGemini

ROOT = Path(__file__).parents[1]
RULES = ROOT / "config" / "coding-rules.yaml"
THRESHOLDS = ROOT / "config" / "thresholds.yaml"
REPLAY = ROOT / "data" / "oder-replay.csv"


def _build(tmp_path: Path, gemini: GeminiClient, coding_agent) -> BridgeService:
    return BridgeService(
        repository=Repository(tmp_path / "test.db"),
        coding_agent=coding_agent,
        thresholds=ThresholdPolicy(THRESHOLDS),
        fhir_client=FhirClient("http://unused.test/fhir", write_enabled=False, timeout=1),
        intake=UnstructuredIntake(gemini),
        briefing_writer=BriefingWriter(gemini),
        replay_path=REPLAY,
    )


@pytest.fixture
def curated_agent() -> ReviewedCodingAgent:
    return ReviewedCodingAgent(RULES)


@pytest.fixture
def service(tmp_path: Path, curated_agent: ReviewedCodingAgent) -> BridgeService:
    """Deterministic pipeline with AI switched off (no key)."""
    return _build(tmp_path, GeminiClient(api_key="", model="gemini-test"), curated_agent)


@pytest.fixture
def fake_gemini() -> FakeGemini:
    return FakeGemini()


@pytest.fixture
def ai_service(
    tmp_path: Path, curated_agent: ReviewedCodingAgent, fake_gemini: FakeGemini
) -> BridgeService:
    """Full pipeline with a stubbed Gemini transport."""
    agent = GeminiCodingAgent(curated_agent, fake_gemini, assist_mode=AssistMode.ALWAYS)
    return _build(tmp_path, fake_gemini, agent)
