"""Open DART API client and disclosure cleaning pipeline."""

from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup, Comment
from fastapi import HTTPException, status
from markdownify import markdownify as md

from app.core.config import Settings, get_settings
from app.schemas.dart import (
    CompanyDisclosuresResponse,
    DisclosureItem,
    StructuredMetric,
)

logger = logging.getLogger(__name__)

OPENDART_BASE = "https://opendart.fss.or.kr/api"
DART_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

# Heuristic labels commonly found in Korean filings
_METRIC_LABEL_HINTS = (
    "매출",
    "영업이익",
    "당기순이익",
    "순이익",
    "자산총계",
    "부채총계",
    "자본총계",
    "영업수익",
    "매출액",
    "매출총이익",
    "법인세",
    "EPS",
    "주당순이익",
    "ROE",
    "ROA",
)

_NUMBER_RE = re.compile(
    r"^[\(\-−]?\s*[\d,]+(?:\.\d+)?\s*[\)%]?\s*(?:백만|천|억|조|원|%)?$"
)


class DartService:
    """Async Open DART client with corp-code cache and HTML→Markdown cleaning."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._stock_to_corp: dict[str, tuple[str, str]] | None = None

    def _require_api_key(self) -> str:
        key = (self.settings.dart_api_key or "").strip()
        if not key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "DART_API_KEY가 설정되지 않았습니다. "
                    ".env에 Open DART API 키를 설정한 뒤 다시 시도하세요."
                ),
            )
        return key

    async def get_company_disclosures(
        self,
        stock_code: str,
        limit: int = 5,
    ) -> CompanyDisclosuresResponse:
        """Resolve stock_code → corp_code, fetch recent filings, clean bodies."""
        api_key = self._require_api_key()
        corp_code, corp_name = await self.resolve_corp_by_stock(stock_code, api_key)

        listings = await self.fetch_disclosure_list(
            api_key=api_key,
            corp_code=corp_code,
            page_count=limit,
        )

        disclosures: list[DisclosureItem] = []
        warnings: list[str] = []

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            for item in listings[:limit]:
                rcept_no = str(item.get("rcept_no", "")).strip()
                if not rcept_no:
                    continue

                clean_md = ""
                metrics: list[StructuredMetric] = []
                try:
                    raw_html = await self.fetch_document_html(client, api_key, rcept_no)
                    clean_md = clean_html_to_markdown(raw_html)
                    metrics = extract_structured_metrics(raw_html, clean_md)
                except Exception as exc:  # noqa: BLE001 — partial success OK
                    logger.warning("Failed to clean document %s: %s", rcept_no, exc)
                    warnings.append(f"{rcept_no}: 원문 정제 실패 ({exc})")
                    clean_md = (
                        f"(원문 취득/정제 실패) 보고서: {item.get('report_nm', '')}\n"
                        f"뷰어: {DART_VIEWER_URL.format(rcept_no=rcept_no)}"
                    )

                disclosures.append(
                    DisclosureItem(
                        rcept_no=rcept_no,
                        report_nm=str(item.get("report_nm") or ""),
                        rcept_dt=str(item.get("rcept_dt") or ""),
                        corp_code=str(item.get("corp_code") or corp_code),
                        corp_name=str(item.get("corp_name") or corp_name or ""),
                        stock_code=str(item.get("stock_code") or stock_code).strip()
                        or stock_code,
                        flr_nm=item.get("flr_nm"),
                        rm=item.get("rm") or None,
                        viewer_url=DART_VIEWER_URL.format(rcept_no=rcept_no),
                        clean_markdown=clean_md,
                        structured_metrics=metrics,
                    )
                )

        message = None
        if warnings:
            message = "일부 공시 원문 정제에 실패했습니다: " + "; ".join(warnings[:5])
        if not disclosures:
            message = message or "해당 조건의 공시가 없습니다."

        return CompanyDisclosuresResponse(
            stock_code=stock_code,
            corp_code=corp_code,
            corp_name=corp_name,
            limit=limit,
            count=len(disclosures),
            disclosures=disclosures,
            fetched_at=datetime.now(timezone.utc),
            message=message,
        )

    async def resolve_corp_by_stock(
        self,
        stock_code: str,
        api_key: str,
    ) -> tuple[str, str]:
        """Map 6-digit stock_code to (corp_code, corp_name)."""
        mapping = await self._ensure_corp_code_cache(api_key)
        entry = mapping.get(stock_code)
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"종목코드 {stock_code}에 해당하는 DART 기업을 찾을 수 없습니다.",
            )
        return entry

    async def _ensure_corp_code_cache(self, api_key: str) -> dict[str, tuple[str, str]]:
        if self._stock_to_corp is not None:
            return self._stock_to_corp

        url = f"{OPENDART_BASE}/corpCode.xml"
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params={"crtfc_key": api_key})
            response.raise_for_status()
            content = response.content

        if content[:1] == b"{":
            # JSON error payload instead of zip
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Open DART corpCode 응답 오류: {content[:500]!r}",
            )

        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                # Usually CORPCODE.xml
                names = zf.namelist()
                xml_name = next(
                    (n for n in names if n.lower().endswith(".xml")),
                    names[0] if names else None,
                )
                if not xml_name:
                    raise ValueError("corpCode zip에 XML이 없습니다.")
                xml_bytes = zf.read(xml_name)
        except zipfile.BadZipFile as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Open DART corpCode.zip 파싱에 실패했습니다.",
            ) from exc

        mapping: dict[str, tuple[str, str]] = {}
        root = ET.fromstring(xml_bytes)
        for node in root.iter():
            tag = _local_tag(node.tag)
            if tag != "list":
                continue
            corp_code = _child_text(node, "corp_code")
            corp_name = _child_text(node, "corp_name")
            stock = _child_text(node, "stock_code").strip()
            if stock and corp_code:
                mapping[stock] = (corp_code, corp_name)

        self._stock_to_corp = mapping
        logger.info("Loaded %d stock→corp mappings from Open DART", len(mapping))
        return mapping

    async def fetch_disclosure_list(
        self,
        *,
        api_key: str,
        corp_code: str,
        page_count: int = 5,
        bgn_de: str | None = None,
        end_de: str | None = None,
    ) -> list[dict[str, Any]]:
        """Call Open DART list.json for recent disclosures."""
        today = datetime.now(timezone.utc)
        if end_de is None:
            end_de = today.strftime("%Y%m%d")
        if bgn_de is None:
            bgn_de = (today - timedelta(days=365 * 3)).strftime("%Y%m%d")

        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_count": min(max(page_count, 1), 100),
            "page_no": 1,
            "sort": "date",
            "sort_mth": "desc",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{OPENDART_BASE}/list.json", params=params)
            response.raise_for_status()
            payload = response.json()

        status_code = str(payload.get("status", ""))
        if status_code == "013":
            # No data
            return []
        if status_code != "000":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"Open DART list.json 오류 "
                    f"(status={status_code}): {payload.get('message')}"
                ),
            )
        return list(payload.get("list") or [])

    async def fetch_document_html(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        rcept_no: str,
    ) -> str:
        """Download document.zip and concatenate readable HTML/XML text."""
        response = await client.get(
            f"{OPENDART_BASE}/document.xml",
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
        )
        response.raise_for_status()
        content = response.content

        if content[:1] == b"{":
            raise RuntimeError(f"document API JSON 오류: {content[:300]!r}")

        parts: list[str] = []
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in sorted(zf.namelist()):
                    lower = name.lower()
                    if not (
                        lower.endswith((".htm", ".html", ".xml", ".xhtml"))
                        or "report" in lower
                    ):
                        continue
                    raw = zf.read(name)
                    text = _decode_bytes(raw)
                    if text.strip():
                        parts.append(text)
        except zipfile.BadZipFile as exc:
            raise RuntimeError("document.zip이 유효하지 않습니다.") from exc

        if not parts:
            # Fallback: public viewer page (often JS-heavy; still try body text)
            viewer = await client.get(
                DART_VIEWER_URL.format(rcept_no=rcept_no),
                headers={"User-Agent": "AgentHub-DART-Cleaner/1.0"},
            )
            if viewer.status_code == 200 and viewer.text:
                return viewer.text
            raise RuntimeError("공시 원문 파일이 zip에 없습니다.")

        # Prefer the largest HTML-like part as main body
        parts.sort(key=len, reverse=True)
        return "\n\n".join(parts[:5])


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _child_text(node: ET.Element, name: str) -> str:
    for child in list(node):
        if _local_tag(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8", "cp949", "euc-kr", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def clean_html_to_markdown(html: str) -> str:
    """Strip scripts/styles/comments/noise and convert tables to Markdown."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "meta", "link", "head"]):
        tag.decompose()

    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Drop empty noisy wrappers often found in DART docs
    for tag in soup.find_all(["font", "span"]):
        if not tag.get_text(strip=True) and not tag.find("img"):
            tag.decompose()

    body = soup.body or soup
    markdown = md(
        str(body),
        heading_style="ATX",
        bullets="-",
        strip=["img"],
        escape_asterisks=False,
        escape_underscores=False,
    )
    # Collapse excessive whitespace / blank lines
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip()


def extract_structured_metrics(
    html: str,
    markdown: str = "",
) -> list[StructuredMetric]:
    """Best-effort extraction of key financial figures from tables / markdown."""
    metrics: list[StructuredMetric] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        header_cells = [
            c.get_text(" ", strip=True)
            for c in rows[0].find_all(["th", "td"])
        ]

        for row in rows[1:] if len(rows) > 1 else rows:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if len(cells) < 2:
                continue

            label = cells[0]
            if not label or not any(h in label for h in _METRIC_LABEL_HINTS):
                continue

            for idx, value in enumerate(cells[1:], start=1):
                if not value or not _looks_like_number(value):
                    continue
                period = header_cells[idx] if idx < len(header_cells) else None
                unit = _guess_unit(value, label)
                key = (label, value, period)
                if key in seen:
                    continue
                seen.add(key)
                metrics.append(
                    StructuredMetric(
                        label=label,
                        value=value,
                        unit=unit,
                        period=period or None,
                    )
                )
                if len(metrics) >= 40:
                    return metrics

    # Fallback: scan markdown lines like "매출액 | 123,456"
    if not metrics and markdown:
        for line in markdown.splitlines():
            if "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 2:
                continue
            label = parts[0]
            if not any(h in label for h in _METRIC_LABEL_HINTS):
                continue
            for value in parts[1:]:
                if _looks_like_number(value):
                    key = (label, value, None)
                    if key in seen:
                        continue
                    seen.add(key)
                    metrics.append(
                        StructuredMetric(
                            label=label,
                            value=value,
                            unit=_guess_unit(value, label),
                            period=None,
                        )
                    )
                    break
            if len(metrics) >= 40:
                break

    return metrics


def _looks_like_number(text: str) -> bool:
    cleaned = text.replace(" ", "")
    if not cleaned or cleaned in {"-", "—", "–", "해당없음", "N/A"}:
        return False
    return bool(_NUMBER_RE.match(cleaned))


def _guess_unit(value: str, label: str) -> str | None:
    if "%" in value or "률" in label or "율" in label:
        return "%"
    if "백만" in value:
        return "백만원"
    if "억" in value:
        return "억원"
    if "원" in value:
        return "원"
    return None


# Module-level singleton for corp-code cache reuse across requests
_dart_service: DartService | None = None


def get_dart_service() -> DartService:
    global _dart_service
    if _dart_service is None:
        _dart_service = DartService()
    return _dart_service
