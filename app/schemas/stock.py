"""Stock-related schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class StockSummaryResponse(BaseModel):
    code: str = Field(..., description="종목 코드", examples=["005930"])
    name: str | None = Field(None, description="종목명", examples=["삼성전자"])
    market: str | None = Field(None, description="시장 구분", examples=["KOSPI"])
    price: float | None = Field(None, description="현재가", examples=[72000.0])
    change: float | None = Field(None, description="전일 대비 등락", examples=[500.0])
    change_percent: float | None = Field(
        None, description="전일 대비 등락률(%)", examples=[0.7]
    )
    volume: int | None = Field(None, description="거래량", examples=[1234567])
    currency: str = Field("KRW", description="통화")
    updated_at: datetime = Field(..., description="데이터 기준 시각 (UTC)")
    message: str | None = Field(None, description="부가 메시지")
