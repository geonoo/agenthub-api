"""Shared pytest fixtures for AgentHub API tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.security import rate_limiter
from app.db.session import init_db, reset_engine
from app.main import app
from app.services import dart_service as dart_service_module
from app.services import finance_service as finance_service_module
from app.services.dart_service import DartService


TEST_API_KEY = "test-api-key-agenthub"
TEST_MASTER_API_KEY = "test-master-key"
TEST_DART_API_KEY = "test-dart-api-key"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Settings:
    """Isolated settings + fresh SQLite DB per test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("API_KEY", TEST_API_KEY)
    monkeypatch.setenv("MASTER_API_KEY", TEST_MASTER_API_KEY)
    monkeypatch.setenv("DART_API_KEY", TEST_DART_API_KEY)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("FREE_TIER_DAILY_LIMIT", "1000")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    init_db()
    return get_settings()


@pytest.fixture
def client(settings: Settings) -> TestClient:
    dart_service_module._dart_service = None
    finance_service_module._finance_service = None
    with TestClient(app) as test_client:
        yield test_client
    dart_service_module._dart_service = None
    finance_service_module._finance_service = None
    get_settings.cache_clear()
    reset_engine()


@pytest.fixture
def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-API-KEY": settings.api_key}


@pytest.fixture
def master_auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-API-KEY": settings.master_api_key}


@pytest.fixture
def dart_service(settings: Settings) -> DartService:
    return DartService(settings=settings)
