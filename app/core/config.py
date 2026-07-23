"""Application settings loaded from environment variables."""

from functools import lru_cache

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

    # Rate limit (per API key / IP)
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    # CORS
    cors_origins: str = "https://agenthub.co.kr,https://api.agenthub.co.kr"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Open DART (금융감독원 전자공시)
    dart_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def valid_api_keys(self) -> set[str]:
        """Accepted X-API-KEY values (MASTER_API_KEY takes precedence alongside API_KEY)."""
        keys = {self.api_key.strip()} if self.api_key.strip() else set()
        if self.master_api_key.strip():
            keys.add(self.master_api_key.strip())
        return keys


@lru_cache
def get_settings() -> Settings:
    return Settings()
