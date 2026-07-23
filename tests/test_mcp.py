"""MCP JSON-RPC / SSE / tools tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.security import is_auth_exempt
from app.schemas.dart import CompanyDisclosuresResponse
from app.schemas.finance import FinanceNewsResponse


def test_mcp_paths_are_auth_exempt():
    for path in (
        "/mcp",
        "/mcp/sse",
        "/mcp/messages",
        "/mcp/schema",
        "/mcp/tools",
        "/api/v1/mcp",
        "/api/v1/mcp/sse",
        "/api/v1/mcp/messages",
    ):
        assert is_auth_exempt(path), path


def test_mcp_initialize_public_no_auth(client):
    """Handshake must succeed without X-API-KEY and without DB quota work."""
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["serverInfo"]["name"] == "agenthub"
    assert "protocolVersion" in body["result"]


def test_mcp_initialize_via_messages(client):
    response = client.post(
        "/mcp/messages",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    assert response.json()["result"]["capabilities"]["tools"]["listChanged"] is False


def test_mcp_tools_list_public(client):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200
    names = {t["name"] for t in response.json()["result"]["tools"]}
    assert names == {"get_dart_disclosures", "get_stock_news"}


@pytest.mark.asyncio
async def test_mcp_sse_emits_endpoint_immediately():
    """First SSE event must advertise /mcp/messages without waiting on DB/auth."""
    from starlette.requests import Request

    from app.api.v1.endpoints import mcp as mcp_mod

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/mcp/sse",
        "raw_path": b"/mcp/sse",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    request = Request(scope)
    response = await mcp_mod.mcp_sse(request)
    assert response.media_type == "text/event-stream"
    agen = response.body_iterator
    first = await agen.__anext__()
    if isinstance(first, memoryview):
        first = first.tobytes()
    if isinstance(first, bytes):
        first = first.decode()
    assert "event: endpoint" in first
    assert "/mcp/messages" in first
    await agen.aclose()


def test_mcp_schema(client):
    response = client.get("/mcp/schema")
    assert response.status_code == 200
    assert len(response.json()["tools"]) == 2


def test_mcp_rest_tools_alias(client):
    response = client.get("/mcp/tools")
    assert response.status_code == 200
    assert len(response.json()["tools"]) == 2


def test_mcp_api_v1_alias(client):
    response = client.get("/api/v1/mcp/tools")
    assert response.status_code == 200


def test_mcp_call_get_stock_news(client, monkeypatch):
    stub = FinanceNewsResponse(
        stock_code="005930",
        limit=1,
        count=0,
        items=[],
        fetched_at=datetime.now(timezone.utc),
        message="none",
    )
    mock_finance = AsyncMock()
    mock_finance.get_stock_news = AsyncMock(return_value=stub)
    mock_dart = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.endpoints.mcp.get_finance_service",
        lambda: mock_finance,
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.mcp.get_dart_service",
        lambda: mock_dart,
    )
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_stock_news",
                "arguments": {"stock_code": "005930", "limit": 1},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()["result"]
    assert body["isError"] is False
    mock_finance.get_stock_news.assert_awaited_once()


def test_mcp_call_get_dart_disclosures(client, monkeypatch):
    stub = CompanyDisclosuresResponse(
        stock_code="005930",
        corp_code="00126380",
        corp_name="삼성전자",
        limit=1,
        count=0,
        disclosures=[],
        fetched_at=datetime.now(timezone.utc),
        message="none",
    )
    mock_dart = AsyncMock()
    mock_dart.get_company_disclosures = AsyncMock(return_value=stub)
    mock_finance = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.endpoints.mcp.get_dart_service",
        lambda: mock_dart,
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.mcp.get_finance_service",
        lambda: mock_finance,
    )
    response = client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_dart_disclosures",
                "arguments": {"stock_code": "005930", "limit": 1},
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
