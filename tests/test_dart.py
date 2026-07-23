"""DART disclosure API & cleaning unit tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.schemas.dart import CompanyDisclosuresResponse, DisclosureItem
from app.services.dart_service import (
    DartService,
    clean_html_to_markdown,
    extract_structured_metrics,
    get_dart_service,
)

SAMPLE_HTML = """
<html>
<head><style>.x{color:red}</style><script>alert(1)</script></head>
<body>
  <!-- cmt -->
  <h1>분기보고서</h1>
  <table>
    <tr><th>과목</th><th>당기</th></tr>
    <tr><td>매출액</td><td>100,000</td></tr>
    <tr><td>영업이익</td><td>12,500</td></tr>
  </table>
</body>
</html>
"""


def test_clean_html_to_markdown():
    md = clean_html_to_markdown(SAMPLE_HTML)
    assert "alert" not in md
    assert "color:red" not in md
    assert "분기보고서" in md
    assert "|" in md
    assert "매출액" in md


def test_extract_structured_metrics():
    metrics = extract_structured_metrics(SAMPLE_HTML)
    labels = {m.label for m in metrics}
    assert "매출액" in labels
    assert "영업이익" in labels


def test_dart_requires_api_key(client):
    response = client.get(
        "/api/v1/dart/company-disclosures",
        params={"stock_code": "005930"},
    )
    assert response.status_code == 401


def test_dart_invalid_stock_code(client, auth_headers):
    response = client.get(
        "/api/v1/dart/company-disclosures",
        params={"stock_code": "ABC"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_dart_missing_upstream_key_returns_503(client, auth_headers, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    response = client.get(
        "/api/v1/dart/company-disclosures",
        params={"stock_code": "005930"},
        headers=auth_headers,
    )
    assert response.status_code == 503
    get_settings.cache_clear()


def test_dart_company_disclosures_ok(client, auth_headers):
    stub = CompanyDisclosuresResponse(
        stock_code="005930",
        corp_code="00126380",
        corp_name="삼성전자",
        limit=1,
        count=1,
        disclosures=[
            DisclosureItem(
                rcept_no="20240101000001",
                report_nm="분기보고서",
                rcept_dt="20240101",
                corp_code="00126380",
                corp_name="삼성전자",
                stock_code="005930",
                flr_nm="삼성전자",
                rm=None,
                viewer_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240101000001",
                clean_markdown="# 분기보고서",
                structured_metrics=[],
            )
        ],
        fetched_at=datetime.now(timezone.utc),
        message=None,
    )
    mock_service = AsyncMock(spec=DartService)
    mock_service.get_company_disclosures = AsyncMock(return_value=stub)
    client.app.dependency_overrides[get_dart_service] = lambda: mock_service
    try:
        response = client.get(
            "/api/v1/dart/company-disclosures",
            params={"stock_code": "005930", "limit": 1},
            headers=auth_headers,
        )
    finally:
        client.app.dependency_overrides.pop(get_dart_service, None)

    assert response.status_code == 200
    assert response.json()["corp_name"] == "삼성전자"


@pytest.mark.asyncio
async def test_dart_service_require_api_key_empty():
    service = DartService(settings=Settings(dart_api_key=""))
    with pytest.raises(HTTPException) as exc_info:
        service._require_api_key()
    assert exc_info.value.status_code == 503


def test_dart_openapi_llm_docs(client):
    schema = client.get("/openapi.json").json()
    path = schema["paths"]["/api/v1/dart/company-disclosures"]["get"]
    assert "Token-Optimized" in path["summary"]
    assert "LLM-friendly" in path["description"]
