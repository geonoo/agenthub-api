"""Self-service API key issuance with email verification + quota tests."""

from __future__ import annotations

from app.db.session import get_session_factory
from app.services import key_service
from app.services.key_service import hash_api_key


def _verify_and_issue(client, email: str) -> str:
    """Send code (Resend skipped in test), verify with DB code, then issue key."""
    send = client.post("/api/v1/auth/send-code", json={"email": email})
    assert send.status_code == 200, send.text

    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        from sqlalchemy import select
        from app.db.models import EmailVerification

        row = db.scalar(
            select(EmailVerification)
            .where(EmailVerification.email == email.lower())
            .order_by(EmailVerification.created_at.desc())
        )
        assert row is not None
        code = row.code
    finally:
        db.close()

    verify = client.post(
        "/api/v1/auth/verify-code",
        json={"email": email, "code": code},
    )
    assert verify.status_code == 200, verify.text

    issued = client.post("/api/v1/auth/issue-key", json={"email": email})
    assert issued.status_code == 200, issued.text
    return issued.json()["api_key"]


def test_send_and_verify_code(client):
    email = "verify@example.com"
    assert client.post("/api/v1/auth/send-code", json={"email": email}).status_code == 200

    from sqlalchemy import select
    from app.db.models import EmailVerification

    db = get_session_factory()()
    try:
        row = db.scalar(
            select(EmailVerification)
            .where(EmailVerification.email == email)
            .order_by(EmailVerification.created_at.desc())
        )
        code = row.code
    finally:
        db.close()

    ok = client.post("/api/v1/auth/verify-code", json={"email": email, "code": code})
    assert ok.status_code == 200
    assert ok.json()["verified"] is True


def test_issue_key_requires_verification(client):
    response = client.post(
        "/api/v1/auth/issue-key",
        json={"email": "noverif@example.com"},
    )
    assert response.status_code == 403


def test_issue_key_returns_raw_once(client):
    raw = _verify_and_issue(client, "dev@example.com")
    assert raw.startswith("ah_live_")


def test_issued_key_stored_as_sha256_not_plaintext(client):
    raw = _verify_and_issue(client, "hash@example.com")
    digest = hash_api_key(raw)
    db = get_session_factory()()
    try:
        row = key_service.find_active_key_by_raw(db, raw)
        assert row is not None
        assert row.key_hash == digest
        assert row.key_prefix != raw
    finally:
        db.close()


def test_issued_key_authenticates(client):
    issued = _verify_and_issue(client, "auth@example.com")
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
    issued = _verify_and_issue(client, "usage@example.com")
    client.get(
        "/api/v1/stock/summary",
        params={"code": "005930"},
        headers={"X-API-KEY": issued},
    )
    usage = client.get("/api/v1/auth/usage", headers={"X-API-KEY": issued})
    assert usage.status_code == 200
    body = usage.json()
    assert body["used_today"] >= 1
    assert body["plan"] == "free"


def test_daily_quota_returns_429(client):
    issued = _verify_and_issue(client, "quota@example.com")
    db = get_session_factory()()
    try:
        row = key_service.find_active_key_by_raw(db, issued)
        row.daily_limit = 2
        db.commit()
    finally:
        db.close()

    headers = {"X-API-KEY": issued}
    codes = [
        client.get(
            "/api/v1/stock/summary",
            params={"code": "005930"},
            headers=headers,
        ).status_code
        for _ in range(4)
    ]
    assert codes.count(200) == 2
    assert 429 in codes


def test_wrong_code_rejected(client):
    email = "badcode@example.com"
    assert client.post("/api/v1/auth/send-code", json={"email": email}).status_code == 200
    bad = client.post(
        "/api/v1/auth/verify-code",
        json={"email": email, "code": "000000"},
    )
    assert bad.status_code == 400


def test_landing_has_key_cta(client):
    html = client.get("/").text
    assert "API Key" in html
    assert "send-code" in html or "인증번호" in html


def test_dashboard_page(client):
    assert client.get("/dashboard").status_code == 200
