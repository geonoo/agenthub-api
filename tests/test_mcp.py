"""MCP JSON-RPC / tools tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.schemas.dart import CompanyDisclosuresResponse
from app.schemas.finance import FinanceNewsResponse
from app.services.dart_service import get_dart_service
from app.services.finance_service import get_finance_service


def test_mcp_requires_auth(client):
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401


def test_mcp_tools_list(client, auth_headers):
    response = client.post(
        "/mcp",
        headers=auth_headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200
    result = response.json()["result"]
    names = {t["name"] for t in result["tools"]}
    assert names == {"get_dart_disclosures", "get_stock_news"}


def test_mcp_initialize(client, auth_headers):
    response = client.post(
        "/mcp",
        headers=auth_headers,
        json={"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "agenthub"


def test_mcp_rest_tools_alias(client, auth_headers):
    response = client.get("/mcp/tools", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()["tools"]) == 2


def test_mcp_api_v1_alias(client, auth_headers):
    response = client.get("/api/v1/mcp/tools", headers=auth_headers)
    assert response.status_code == 200


def test_mcp_call_get_stock_news(client, auth_headers):
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
    client.app.dependency_overrides[get_finance_service] = lambda: mock_finance
    try:
        response = client.post(
            "/mcp",
            headers=auth_headers,
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
    finally:
        client.app.dependency_overrides.pop(get_finance_service, None)

    assert response.status_code == 200
    body = response.json()["result"]
    assert body["isError"] is False
    mock_finance.get_stock_news.assert_awaited_once()


def test_mcp_call_get_dart_disclosures(client, auth_headers):
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
    client.app.dependency_overrides[get_dart_service] = lambda: mock_dart
    try:
        response = client.post(
            "/mcp",
            headers=auth_headers,
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
    finally:
        client.app.dependency_overrides.pop(get_dart_service, None)

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
