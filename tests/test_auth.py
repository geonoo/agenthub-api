"""API Key auth & rate-limit tests."""

import pytest
from fastapi import HTTPException

from app.core.config import Settings, get_settings
from app.core.security import rate_limiter, verify_api_key


@pytest.mark.asyncio
async def test_verify_api_key_missing(settings):
    settings = Settings(api_key="secret", master_api_key="")
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(api_key=None, settings=settings)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_api_key_invalid_returns_401(settings):
    settings = Settings(api_key="secret", master_api_key="master")
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(api_key="nope", settings=settings)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_api_key_accepts_master_key(settings):
    settings = Settings(api_key="secret", master_api_key="master-secret")
    result = await verify_api_key(api_key="master-secret", settings=settings)
    assert result == "master-secret"


def test_protected_route_requires_api_key(client):
    response = client.get("/api/v1/stock/summary", params={"code": "005930"})
    assert response.status_code == 401


def test_protected_route_rejects_invalid_key(client):
    response = client.get(
        "/api/v1/stock/summary",
        params={"code": "005930"},
        headers={"X-API-KEY": "wrong-key"},
    )
    assert response.status_code == 401


def test_master_api_key_works(client, master_auth_headers):
    response = client.get(
        "/api/v1/stock/summary",
        params={"code": "005930"},
        headers=master_auth_headers,
    )
    assert response.status_code == 200


def test_docs_and_static_are_public(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/static/index.html").status_code == 200
    assert client.get("/dashboard").status_code == 200


def test_rate_limit_middleware(client, auth_headers, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    rate_limiter.reset()

    codes = []
    for _ in range(5):
        codes.append(
            client.get(
                "/api/v1/stock/summary",
                params={"code": "005930"},
                headers=auth_headers,
            ).status_code
        )

    assert 429 in codes
    assert codes.count(200) >= 1
    get_settings.cache_clear()
