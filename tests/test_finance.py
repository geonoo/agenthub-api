"""Finance (Naver) news API tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.schemas.finance import FinanceNewsItem, FinanceNewsResponse
from app.services.finance_service import (
    clean_html_to_markdown,
    get_finance_service,
    parse_news_list_html,
)

LIST_HTML = """
<html><body>
<table class="type5">
  <tr>
    <td class="title"><a href="/item/news_read.naver?article_id=1&amp;code=005930">실적 호조 전망</a></td>
    <td class="info">한국경제</td>
    <td class="date">2024.05.15 09:30</td>
  </tr>
  <tr>
    <td class="title"><a href="/item/news_read.naver?article_id=2&amp;code=005930">신규 수주 공시</a></td>
    <td class="info">매일경제</td>
    <td class="date">2024.05.14 11:00</td>
  </tr>
</table>
</body></html>
"""

ARTICLE_HTML = """
<html>
<head><script>track()</script><style>.ad{}</style></head>
<body>
  <div id="news_read">
    <h2>실적 호조 전망</h2>
    <p>영업이익이 증가했습니다.</p>
    <div class="ad_area">광고클릭</div>
  </div>
</body>
</html>
"""


def test_parse_news_list_html():
    items = parse_news_list_html(LIST_HTML, limit=5)
    assert len(items) == 2
    assert items[0]["title"] == "실적 호조 전망"
    assert "news_read" in (items[0]["url"] or "")


def test_clean_article_html():
    md = clean_html_to_markdown(ARTICLE_HTML)
    assert "track()" not in md
    assert "광고클릭" not in md
    assert "영업이익" in md


def test_finance_news_requires_auth(client):
    response = client.get("/api/v1/finance/news", params={"stock_code": "005930"})
    assert response.status_code == 401


def test_finance_news_invalid_stock_code(client, auth_headers):
    response = client.get(
        "/api/v1/finance/news",
        params={"stock_code": "59"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_finance_news_ok(client, auth_headers):
    stub = FinanceNewsResponse(
        stock_code="005930",
        limit=1,
        count=1,
        items=[
            FinanceNewsItem(
                title="실적 호조 전망",
                url="https://finance.naver.com/x",
                source="한국경제",
                published_at="2024.05.15 09:30",
                clean_markdown="# 실적 호조 전망\n\n본문",
            )
        ],
        fetched_at=datetime.now(timezone.utc),
        message=None,
    )
    mock_service = AsyncMock()
    mock_service.get_stock_news = AsyncMock(return_value=stub)
    client.app.dependency_overrides[get_finance_service] = lambda: mock_service
    try:
        response = client.get(
            "/api/v1/finance/news",
            params={"stock_code": "005930", "limit": 1},
            headers=auth_headers,
        )
    finally:
        client.app.dependency_overrides.pop(get_finance_service, None)

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["title"] == "실적 호조 전망"


def test_finance_openapi_llm_docs(client):
    schema = client.get("/openapi.json").json()
    path = schema["paths"]["/api/v1/finance/news"]["get"]
    assert "Token-Optimized" in path["summary"]
    assert "minimize" in path["description"].lower() or "token" in path["description"].lower()
