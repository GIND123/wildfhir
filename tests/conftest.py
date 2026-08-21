from pathlib import Path

import pytest

from aquafhir.briefing import BriefingWriter
from aquafhir.coding import ReviewedCodingAgent
from aquafhir.coding_llm import GeminiCodingAgent
from aquafhir.config import AssistMode
from aquafhir.fhir import FhirClient
from aquafhir.gemini import GeminiClient
from aquafhir.intake import UnstructuredIntake
from aquafhir.loinc_table import LoincTable
from aquafhir.repository import Repository
from aquafhir.service import BridgeService
from aquafhir.terminology import TerminologyCrosswalk
from aquafhir.thresholds import ThresholdPolicy
from aquafhir.umls import UMLSClient
from tests.fakes import FakeGemini, FakeUMLS

ROOT = Path(__file__).parents[1]
RULES = ROOT / "config" / "coding-rules.yaml"
THRESHOLDS = ROOT / "config" / "thresholds.yaml"
REPLAY = ROOT / "data" / "oder-replay.csv"


def _build(
    tmp_path: Path,
    gemini: GeminiClient,
    coding_agent,
    umls: UMLSClient | None = None,
    loinc_table: LoincTable | None = None,
) -> BridgeService:
    return BridgeService(
        repository=Repository(tmp_path / "test.db"),
        coding_agent=coding_agent,
        thresholds=ThresholdPolicy(THRESHOLDS),
        fhir_client=FhirClient("http://unused.test/fhir", write_enabled=False, timeout=1),
        intake=UnstructuredIntake(gemini),
        briefing_writer=BriefingWriter(gemini),
        terminology=TerminologyCrosswalk(
            umls or UMLSClient(api_key=""), loinc_table=loinc_table
        ),
        replay_path=REPLAY,
    )


def build_loinc_table(tmp_path: Path) -> LoincTable:
    """A tiny stand-in for the licensed table, so tests stay fast and offline."""
    path = tmp_path / "LoincTableCore.csv"
    path.write_text(
        '"LOINC_NUM","COMPONENT","SYSTEM","SCALE_TYP","LONG_COMMON_NAME","STATUS"\n'
        '"9481-3","pH","Water","SemiQn","pH of Water","ACTIVE"\n'
        '"12530-2","Chloride","Water","Qn","Chloride [Moles/volume] in Water","ACTIVE"\n'
        '"87444-6","Electron","Water","Qn","Electron [Electrical Conductivity] of Water","ACTIVE"\n'
        '"10658-3","Cyanobacterium","Water","Nom",'
        '"Cyanobacterium identified in Water by Light microscopy","ACTIVE"\n'
        '"11556-8","Oxygen","Bld","Qn","Oxygen [Partial pressure] in Blood","ACTIVE"\n'
        '"99999-9","pH","Water","Qn","Deprecated pH of Water","DEPRECATED"\n',
        encoding="utf-8",
    )
    return LoincTable(path)


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


@pytest.fixture
def fake_umls() -> FakeUMLS:
    return FakeUMLS()


@pytest.fixture
def umls_service(
    tmp_path: Path, curated_agent: ReviewedCodingAgent, fake_umls: FakeUMLS
) -> BridgeService:
    """Deterministic coding pipeline with a stubbed UMLS transport, no local table."""
    return _build(
        tmp_path, GeminiClient(api_key="", model="gemini-test"), curated_agent, fake_umls
    )


@pytest.fixture
def local_loinc_service(tmp_path: Path, curated_agent: ReviewedCodingAgent) -> BridgeService:
    """Local LOINC table only -- no UMLS key, no network."""
    return _build(
        tmp_path,
        GeminiClient(api_key="", model="gemini-test"),
        curated_agent,
        loinc_table=build_loinc_table(tmp_path),
    )


@pytest.fixture
def hybrid_service(
    tmp_path: Path, curated_agent: ReviewedCodingAgent, fake_umls: FakeUMLS
) -> BridgeService:
    """Both sources: local LOINC first, stubbed UMLS topping up."""
    return _build(
        tmp_path,
        GeminiClient(api_key="", model="gemini-test"),
        curated_agent,
        fake_umls,
        loinc_table=build_loinc_table(tmp_path),
    )
