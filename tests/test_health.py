"""Health endpoint tests."""


def test_health_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "AgentHub API Service"
    assert "timestamp" in data


def test_health_no_auth_required(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
