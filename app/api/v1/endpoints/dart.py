"""DART financial disclosure cleaning endpoints."""

from fastapi import APIRouter, Depends, Query

from app.core.security import verify_api_key
from app.schemas.dart import CompanyDisclosuresResponse
from app.services.dart_service import DartService, get_dart_service

router = APIRouter()


@router.get(
    "/company-disclosures",
    response_model=CompanyDisclosuresResponse,
    summary="Fetch Clean & Token-Optimized Korean DART Corporate Filings",
    description=(
        "Use this tool when you need clean, LLM-friendly Korean DART corporate "
        "filing disclosure data (e.g. quarterly reports, revenue changes, M&A) "
        "without HTML noise to minimize token consumption."
    ),
    dependencies=[Depends(verify_api_key)],
)
async def get_company_disclosures(
    stock_code: str = Query(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description=(
            "한국 상장사 종목코드 6자리. Open DART corp_code로 매핑되어 "
            "최근 공시를 조회합니다. (예: 삼성전자 005930)"
        ),
        examples=["005930"],
    ),
    limit: int = Query(
        5,
        ge=1,
        le=20,
        description=(
            "반환할 최근 공시 개수 (1–20). 각 공시는 Clean Markdown 본문과 "
            "추출된 핵심 재무 지표 JSON을 포함합니다."
        ),
        examples=[5],
    ),
    dart_service: DartService = Depends(get_dart_service),
) -> CompanyDisclosuresResponse:
    return await dart_service.get_company_disclosures(
        stock_code=stock_code,
        limit=limit,
    )
