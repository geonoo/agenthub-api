"""Naver Finance news endpoints."""

from fastapi import APIRouter, Depends, Query

from app.core.security import verify_api_key
from app.schemas.finance import FinanceNewsResponse
from app.services.finance_service import FinanceService, get_finance_service

router = APIRouter()


@router.get(
    "/news",
    response_model=FinanceNewsResponse,
    summary="Fetch Clean & Token-Optimized Korean Stock News",
    description=(
        "Use this tool when you need clean, LLM-friendly Korean stock news and "
        "broker reports from Naver Finance without HTML/ad/JS noise, to minimize "
        "token consumption for agent reasoning."
    ),
    dependencies=[Depends(verify_api_key)],
)
async def get_finance_news(
    stock_code: str = Query(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="한국 상장사 종목코드 6자리 (예: 삼성전자 005930)",
        examples=["005930"],
    ),
    limit: int = Query(
        5,
        ge=1,
        le=20,
        description="반환할 최근 뉴스 개수 (1–20). 각 기사는 Clean Markdown 본문을 포함합니다.",
        examples=[5],
    ),
    finance_service: FinanceService = Depends(get_finance_service),
) -> FinanceNewsResponse:
    return await finance_service.get_stock_news(stock_code=stock_code, limit=limit)
