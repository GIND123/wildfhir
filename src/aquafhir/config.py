from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()

