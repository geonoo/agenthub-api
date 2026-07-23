"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for AgentHub API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "AgentHub API Service"
    app_description: str = (
        "LLM 에이전트 및 개발자를 위한 한국형 데이터/크롤링/정제 API 허브"
    )
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "production"

    # API auth
    api_v1_prefix: str = "/api/v1"
    api_key: str = "change-me-in-production"
    master_api_key: str = ""
    api_key_header: str = "X-API-KEY"

    # Burst rate limit (per key, in-memory) — in addition to daily quota
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    # Free-tier daily quota for issued keys
    free_tier_daily_limit: int = 1000

    # SQLite
    database_url: str = "sqlite:////app/data/agenthub.db"

    # CORS
    cors_origins: str = "https://agenthub.co.kr,https://api.agenthub.co.kr"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Open DART
    dart_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def env_api_keys(self) -> set[str]:
        """Bootstrap keys from env (unlimited quota)."""
        keys: set[str] = set()
        if self.api_key.strip():
            keys.add(self.api_key.strip())
        if self.master_api_key.strip():
            keys.add(self.master_api_key.strip())
        return keys

    @property
    def valid_api_keys(self) -> set[str]:
        """Backward-compatible alias for env keys."""
        return self.env_api_keys

    @property
    def sqlite_path(self) -> Path | None:
        if self.database_url.startswith("sqlite:///"):
            raw = self.database_url.removeprefix("sqlite:///")
            return Path(raw)
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
