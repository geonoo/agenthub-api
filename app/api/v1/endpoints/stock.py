"""Stock summary endpoint skeleton."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.core.security import verify_api_key
from app.schemas.stock import StockSummaryResponse

router = APIRouter()


@router.get(
    "/summary",
    response_model=StockSummaryResponse,
    summary="종목 요약 조회",
    description=(
        "종목 코드 기준 시세/요약 정보를 반환합니다. "
        "현재는 뼈대(stub) 응답이며, 이후 데이터 소스 연동 예정입니다."
    ),
    dependencies=[Depends(verify_api_key)],
)
async def get_stock_summary(
    code: str = Query(
        ...,
        min_length=1,
        max_length=20,
        description="종목 코드 (예: 005930)",
        examples=["005930"],
    ),
) -> StockSummaryResponse:
    # TODO: 실제 시세/크롤링/정제 파이프라인 연동
    return StockSummaryResponse(
        code=code,
        name=None,
        market=None,
        price=None,
        change=None,
        change_percent=None,
        volume=None,
        currency="KRW",
        updated_at=datetime.now(timezone.utc),
        message="스텁 응답입니다. 데이터 소스 연동 후 실제 값이 채워집니다.",
    )
