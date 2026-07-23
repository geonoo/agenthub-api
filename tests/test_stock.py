"""Stock stub + static/OpenAPI smoke tests."""


def test_stock_summary_ok(client, auth_headers):
    response = client.get(
        "/api/v1/stock/summary",
        params={"code": "005930"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["code"] == "005930"


def test_root_landing(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AgentHub" in response.text
    assert "연동 가이드" in response.text
    assert "mcpServers" in response.text
    assert "Claude Desktop" in response.text


def test_favicon(client):
    assert client.get("/favicon.ico").status_code in (200, 204)


def test_openapi_title(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "AgentHub API Service"
    assert "ApiKeyAuth" in schema["components"]["securitySchemes"]
