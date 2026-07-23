"""Naver Finance news / report cleaning service."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Comment
from markdownify import markdownify as md

from app.schemas.finance import FinanceNewsItem, FinanceNewsResponse

logger = logging.getLogger(__name__)

NAVER_NEWS_LIST = "https://finance.naver.com/item/news_news.naver"
NAVER_BASE = "https://finance.naver.com"
USER_AGENT = (
    "Mozilla/5.0 (compatible; AgentHub/0.1; +https://agenthub.co.kr) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class FinanceService:
    """Crawl Naver Finance news, strip noise, return Clean Markdown."""

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def get_stock_news(
        self,
        stock_code: str,
        limit: int = 5,
    ) -> FinanceNewsResponse:
        listings = await self._fetch_news_listings(stock_code, limit=limit)
        items: list[FinanceNewsItem] = []
        warnings: list[str] = []

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
        ) as client:
            for meta in listings[:limit]:
                body_md = meta.get("summary_markdown") or ""
                try:
                    if meta.get("url"):
                        html = await self._fetch_html(client, meta["url"])
                        body_md = clean_html_to_markdown(html) or body_md
                except Exception as exc:  # noqa: BLE001
                    logger.warning("News body fetch failed %s: %s", meta.get("url"), exc)
                    warnings.append(f"{meta.get('title', '')}: 본문 정제 실패")

                items.append(
                    FinanceNewsItem(
                        title=meta["title"],
                        url=meta.get("url"),
                        source=meta.get("source"),
                        published_at=meta.get("published_at"),
                        clean_markdown=body_md or f"# {meta['title']}\n\n(본문 없음)",
                    )
                )

        message = None
        if warnings:
            message = "일부 기사 본문 정제에 실패했습니다: " + "; ".join(warnings[:5])
        if not items:
            message = message or "해당 종목의 뉴스를 찾지 못했습니다."

        return FinanceNewsResponse(
            stock_code=stock_code,
            limit=limit,
            count=len(items),
            items=items,
            fetched_at=datetime.now(timezone.utc),
            message=message,
        )

    async def _fetch_news_listings(
        self,
        stock_code: str,
        limit: int,
    ) -> list[dict]:
        params = {"code": stock_code, "page": "1"}
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
        ) as client:
            response = await client.get(NAVER_NEWS_LIST, params=params)
            response.raise_for_status()
            html = response.text

        return parse_news_list_html(html, limit=limit)

    async def _fetch_html(self, client: httpx.AsyncClient, url: str) -> str:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def parse_news_list_html(html: str, limit: int = 5) -> list[dict]:
    """Parse Naver finance news list table into metadata dicts."""
    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []
    seen_titles: set[str] = set()

    for row in soup.select("table.type5 tr"):
        title_el = row.select_one("td.title a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)

        href = title_el.get("href") or ""
        url = urljoin(NAVER_BASE, href) if href else None
        source_el = row.select_one("td.info")
        date_el = row.select_one("td.date")
        results.append(
            {
                "title": title,
                "url": url,
                "source": source_el.get_text(strip=True) if source_el else None,
                "published_at": date_el.get_text(strip=True) if date_el else None,
                "summary_markdown": f"# {title}",
            }
        )
        if len(results) >= limit:
            break

    # Fallback: any article-like anchors on the page
    if not results:
        for anchor in soup.select("a[href*='news_read'], a[href*='article']"):
            title = anchor.get_text(" ", strip=True)
            if not title or len(title) < 4 or title in seen_titles:
                continue
            seen_titles.add(title)
            href = anchor.get("href") or ""
            results.append(
                {
                    "title": title,
                    "url": urljoin(NAVER_BASE, href) if href else None,
                    "source": None,
                    "published_at": None,
                    "summary_markdown": f"# {title}",
                }
            )
            if len(results) >= limit:
                break

    return results


def clean_html_to_markdown(html: str) -> str:
    """Strip ads/scripts/styles and convert to Clean Markdown."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "iframe",
            "meta",
            "link",
            "head",
            "nav",
            "footer",
            "aside",
        ]
    ):
        tag.decompose()

    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Common ad / chrome selectors on Naver finance pages
    for selector in (
        "#advisorLab",
        ".ad_area",
        ".banner",
        ".link_news",
        "#topNas",
        ".article_btn_wrap",
    ):
        for node in soup.select(selector):
            node.decompose()

    # Prefer article body containers when present
    body = (
        soup.select_one("#news_read")
        or soup.select_one(".article_body")
        or soup.select_one("#content")
        or soup.body
        or soup
    )

    markdown = md(
        str(body),
        heading_style="ATX",
        bullets="-",
        strip=["img"],
        escape_asterisks=False,
        escape_underscores=False,
    )
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    # Drop leftover tracking noise lines
    lines = [
        line
        for line in markdown.splitlines()
        if not re.search(r"(광고|구독하기|카카오톡|네이버페이)", line)
    ]
    return "\n".join(lines).strip()


_finance_service: FinanceService | None = None


def get_finance_service() -> FinanceService:
    global _finance_service
    if _finance_service is None:
        _finance_service = FinanceService()
    return _finance_service
