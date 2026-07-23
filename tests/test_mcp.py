"""MCP JSON-RPC / SSE session transport tests."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

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


def test_mcp_initialize_direct_http(client):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["serverInfo"]["name"] == "agenthub"
    assert "protocolVersion" in body["result"]


def test_mcp_tools_list_public(client):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200
    names = {t["name"] for t in response.json()["result"]["tools"]}
    assert names == {"get_dart_disclosures", "get_stock_news"}


@pytest.mark.asyncio
async def test_mcp_sse_endpoint_includes_session_id():
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
    agen = response.body_iterator
    first = await agen.__anext__()
    if isinstance(first, memoryview):
        first = first.tobytes()
    if isinstance(first, bytes):
        first = first.decode()
    assert "event: endpoint" in first
    assert "/mcp/messages?session_id=" in first
    await agen.aclose()


@pytest.mark.asyncio
async def test_sse_initialize_response_via_message_event(client):
    """POST /messages returns 202; initialize result is pushed on SSE queue."""
    from app.api.v1.endpoints.mcp import sse_hub

    session = await sse_hub.create()
    session_id = session.session_id

    # Simulate client POST initialize to messages endpoint
    response = client.post(
        f"/mcp/messages?session_id={session_id}",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 202

    # Response must appear on the session SSE queue as event: message
    item = await asyncio.wait_for(session.queue.get(), timeout=2.0)
    assert item is not None
    assert item.startswith("event: message\n")
    data_line = [ln for ln in item.splitlines() if ln.startswith("data: ")][0]
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["id"] == 1
    assert payload["result"]["serverInfo"]["name"] == "agenthub"
    assert "protocolVersion" in payload["result"]

    await sse_hub.close(session_id)


def test_messages_requires_session_id(client):
    response = client.post(
        "/mcp/messages",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 400


def test_messages_unknown_session(client):
    response = client.post(
        "/mcp/messages?session_id=does-not-exist",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 404


def test_mcp_schema(client):
    response = client.get("/mcp/schema")
    assert response.status_code == 200
    assert len(response.json()["tools"]) == 2


def test_mcp_rest_tools_alias(client):
    assert client.get("/mcp/tools").status_code == 200
    assert client.get("/api/v1/mcp/tools").status_code == 200


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
    monkeypatch.setattr(
        "app.api.v1.endpoints.mcp.get_finance_service", lambda: mock_finance
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.mcp.get_dart_service", lambda: AsyncMock()
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
    assert response.json()["result"]["isError"] is False


def test_mcp_call_via_sse_session(client, monkeypatch):
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
    monkeypatch.setattr(
        "app.api.v1.endpoints.mcp.get_dart_service", lambda: mock_dart
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.mcp.get_finance_service", lambda: AsyncMock()
    )

    async def _run():
        from app.api.v1.endpoints.mcp import sse_hub

        session = await sse_hub.create()
        sid = session.session_id
        r = client.post(
            f"/mcp/messages?session_id={sid}",
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
        assert r.status_code == 202
        item = await asyncio.wait_for(session.queue.get(), timeout=2.0)
        payload = json.loads(
            [ln for ln in item.splitlines() if ln.startswith("data: ")][0].removeprefix(
                "data: "
            )
        )
        assert payload["result"]["isError"] is False
        await sse_hub.close(sid)

    import anyio

    anyio.run(_run)
