"""Self-service API key issuance, hash storage, and daily quota tests."""

from __future__ import annotations

from app.db.session import get_session_factory
from app.services import key_service
from app.services.key_service import hash_api_key


def test_issue_key_returns_raw_once(client):
    response = client.post(
        "/api/v1/auth/issue-key",
        json={"email": "dev@example.com"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "dev@example.com"
    assert data["api_key"].startswith("ah_live_")
    assert data["daily_limit"] == 1000
    assert data["key_prefix"] == data["api_key"][:12]


def test_issued_key_stored_as_sha256_not_plaintext(client):
    response = client.post(
        "/api/v1/auth/issue-key",
        json={"email": "hash@example.com"},
    )
    raw = response.json()["api_key"]
    digest = hash_api_key(raw)

    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        row = key_service.find_active_key_by_raw(db, raw)
        assert row is not None
        assert row.key_hash == digest
        assert raw not in row.key_hash
        # plaintext must not appear in any column
        assert row.key_prefix != raw
    finally:
        db.close()


def test_issued_key_authenticates(client):
    issued = client.post(
        "/api/v1/auth/issue-key",
        json={"email": "auth@example.com"},
    ).json()["api_key"]

    ok = client.get(
        "/api/v1/stock/summary",
        params={"code": "005930"},
        headers={"X-API-KEY": issued},
    )
    assert ok.status_code == 200


def test_invalid_key_rejected(client):
    response = client.get(
        "/api/v1/stock/summary",
        params={"code": "005930"},
        headers={"X-API-KEY": "ah_live_this_is_invalid"},
    )
    assert response.status_code == 401


def test_usage_endpoint_for_issued_key(client):
    issued = client.post(
        "/api/v1/auth/issue-key",
        json={"email": "usage@example.com"},
    ).json()["api_key"]

    # Generate one billable call
    client.get(
        "/api/v1/stock/summary",
        params={"code": "005930"},
        headers={"X-API-KEY": issued},
    )

    usage = client.get(
        "/api/v1/auth/usage",
        headers={"X-API-KEY": issued},
    )
    assert usage.status_code == 200
    body = usage.json()
    assert body["used_today"] >= 1
    assert body["remaining_today"] == body["daily_limit"] - body["used_today"]
    assert body["plan"] == "free"


def test_daily_quota_returns_429(client):
    issued = client.post(
        "/api/v1/auth/issue-key",
        json={"email": "quota@example.com"},
    ).json()["api_key"]

    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        row = key_service.find_active_key_by_raw(db, issued)
        assert row is not None
        row.daily_limit = 2
        db.commit()
    finally:
        db.close()

    headers = {"X-API-KEY": issued}
    codes = []
    for _ in range(4):
        codes.append(
            client.get(
                "/api/v1/stock/summary",
                params={"code": "005930"},
                headers=headers,
            ).status_code
        )

    assert codes.count(200) == 2
    assert 429 in codes
    assert codes[2] == 429


def test_issue_key_is_public(client):
    assert client.post(
        "/api/v1/auth/issue-key",
        json={"email": "public@example.com"},
    ).status_code == 200


def test_landing_has_key_cta(client):
    html = client.get("/").text
    assert "API Key" in html
    assert "issue-key" in html or "issue-key-form" in html


def test_dashboard_page(client):
    assert client.get("/dashboard").status_code == 200
