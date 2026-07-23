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

    # API
    api_v1_prefix: str = "/api/v1"
    api_key: str = "change-me-in-production"
    api_key_header: str = "X-API-KEY"

    # CORS
    cors_origins: str = "https://agenthub.co.kr,https://api.agenthub.co.kr"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
