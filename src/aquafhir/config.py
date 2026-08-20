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
    replay_data_path: Path = Path("data/oder-replay.csv")

    # --- Gemini co-pilot -------------------------------------------------
    # The key is read from GEMINI_API_KEY. An absent key disables every AI
    # feature; the deterministic pipeline keeps working unchanged.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
