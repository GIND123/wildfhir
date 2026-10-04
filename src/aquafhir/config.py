from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistMode(StrEnum):
    """When the Gemini co-pilot is consulted for terminology coding."""

    OFF = "off"
    AUTO = "auto"
    ALWAYS = "always"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_path: Path = Path("aquafhir.db")
    fhir_base_url: str = "http://localhost:8080/fhir"
    fhir_write_enabled: bool = False
    fhir_timeout_seconds: float = 15.0
    review_confidence_threshold: float = Field(default=0.90, ge=0, le=1)
    webhook_shared_secret: str = "local-demo-secret"
    coding_rules_path: Path = Path("config/coding-rules.yaml")
    thresholds_path: Path = Path("config/thresholds.yaml")
    connectors_path: Path = Path("config/connectors.yaml")
    replay_data_path: Path = Path("data/oder-replay.csv")
    # The twelve real incidents from docs/incidents.md as one file, loadable from
    # the console's replay button the same way the Oder timeline is.
    incidents_data_path: Path = Path("data/incidents.csv")
    # Hosted demos (render.yaml) start from an empty disk. When true, startup
    # loads the twelve incidents so the board shows pending, approved and
    # rejected cards straight away. Off by default: local runs and tests start
    # from whatever database they already have.
    seed_demo_board: bool = False
    # Read from RENDER, which Render sets to "true" in every service it runs.
    # A service created before render.yaml existed never picked up the
    # SEED_DEMO_BOARD line from the blueprint, and the symptom is the one thing
    # a hosted demo cannot afford: an empty board on the page a visitor opens
    # first. Treat "running on Render" as reason enough to seed, so the hosted
    # board fills itself whether or not the dashboard carries the variable.
    render: bool = False

    # --- Gemini co-pilot -------------------------------------------------
    # The key is read from GEMINI_API_KEY. An absent key disables every AI
    # feature; the deterministic pipeline keeps working unchanged.
    gemini_api_key: str = ""
    # `gemini-3.1-pro-preview` writes the best briefings but needs a billed
    # project: a free-tier key answers HTTP 429 for it, which used to look
    # like a silent AI failure on a judge's fresh key. The fallback below is
    # what makes the default safe to ship.
    gemini_model: str = "gemini-3.1-pro-preview"
    # Tried once, automatically, when the pinned model answers 429 (quota) or
    # 404 (retired). Empty disables the fallback. The model that actually
    # answered is what gets recorded on the proposal, never the pinned name.
    gemini_fallback_model: str = "gemini-3.1-flash-lite"
    gemini_api_base: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_seconds: float = 30.0
    gemini_max_output_tokens: int = 2048
    gemini_max_retries: int = 2
    # -1 omits thinkingConfig entirely (for models that do not accept it).
    gemini_thinking_budget: int = 0
    gemini_assist_mode: AssistMode = AssistMode.AUTO
    # Below this deterministic confidence, `auto` mode consults Gemini.
    gemini_assist_below_confidence: float = Field(default=0.95, ge=0, le=1)
    # Ceiling applied to any AI-influenced proposal. It can never reach a
    # value that would read as "safe to publish without a human".
    gemini_confidence_ceiling: float = Field(default=0.95, ge=0, le=1)

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key.strip())

    # --- UMLS terminology crosswalk --------------------------------------
    # Suggests a real LOINC/SNOMED CT code alongside the curated OAH code.
    # Read from UMLS_API_KEY -- the single `apiKey` UTS profile credential
    # (https://documentation.uts.nlm.nih.gov/rest/authentication.html), not
    # an OAuth2 client_id/client_secret pair. An absent key disables the
    # feature only; the OAH coding and FHIR pipeline is unaffected.
    umls_api_key: str = ""
    umls_api_base: str = "https://uts-ws.nlm.nih.gov/rest"
    umls_timeout_seconds: float = 15.0
    umls_max_retries: int = 2
    umls_vocabularies: str = "LNC,SNOMEDCT_US"
    # Issued by NLM during the UMLS *license request* flow. The UTS REST API
    # does not accept them (it wants `apiKey` above), so they are recorded for
    # the integrations page only and never sent anywhere.
    umls_client_id: str = ""
    umls_client_secret: str = ""
    # Published LOINC term table used to reject UMLS results that are LOINC
    # Parts or Metathesaurus-internal ids rather than real LOINC codes. A
    # missing file disables the check with a warning; it never blocks startup.
    loinc_table_path: Path = Path("loinc/LoincTableCore/LoincTableCore.csv")

    # --- GBIF biodiversity crosswalk -------------------------------------
    # Suggests a GBIF Backbone taxon for an organism named in a source label.
    # There is no key to configure: GBIF read calls are unauthenticated, so
    # `gbif_enabled` is a plain switch, kept so this source can be turned off
    # the way every other external dependency can.
    gbif_enabled: bool = True
    gbif_api_base: str = "https://api.gbif.org/v1"
    gbif_timeout_seconds: float = 15.0
    gbif_max_retries: int = 2

    # --- Live connectors -------------------------------------------------
    # Hub'Eau is the French national open-data API for water. Its river
    # quality service (Naiades) is keyless and covers Toulouse, an
    # OneAquaHealth pilot city. Readings it returns are real measurements.
    hubeau_enabled: bool = True
    hubeau_api_base: str = "https://hubeau.eaufrance.fr/api/v2"
    hubeau_timeout_seconds: float = 30.0
    hubeau_max_retries: int = 2
    # Copernicus Data Space Ecosystem. The product catalogue is keyless and
    # answers "which Sentinel-2 scenes cover this site, how cloudy". Computing
    # an index over a site needs the Sentinel Hub Statistical API, which
    # authenticates with an OAuth2 client (client credentials) from
    # https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings.
    sentinel2_enabled: bool = True
    cdse_client_id: str = ""
    cdse_client_secret: str = ""
    cdse_catalogue_base: str = "https://catalogue.dataspace.copernicus.eu/odata/v1"
    cdse_statistics_url: str = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
    cdse_token_url: str = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    )
    cdse_timeout_seconds: float = 60.0
    cdse_max_retries: int = 2

    @property
    def should_seed_demo_board(self) -> bool:
        """Whether startup fills the board. Explicit setting, or any Render service."""
        return self.seed_demo_board or self.render

    @property
    def cdse_enabled(self) -> bool:
        return bool(self.cdse_client_id.strip() and self.cdse_client_secret.strip())

    @property
    def umls_enabled(self) -> bool:
        return bool(self.umls_api_key.strip())

    @property
    def umls_vocabulary_list(self) -> list[str]:
        return [item.strip() for item in self.umls_vocabularies.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
