"""Finance news response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class FinanceNewsItem(BaseModel):
    title: str = Field(..., description="뉴스/리포트 제목", examples=["삼성전자, 실적 개선 전망"])
    url: str | None = Field(None, description="원문 URL")
    source: str | None = Field(None, description="언론사/출처", examples=["한국경제"])
    published_at: str | None = Field(
        None,
        description="게시 시각 원문 문자열",
        examples=["2024.05.15 09:30"],
    )
    clean_markdown: str = Field(
        ...,
        description="광고/스크립트 제거 후 Clean Markdown 본문 (LLM 토큰 절감)",
    )


class FinanceNewsResponse(BaseModel):
    stock_code: str = Field(..., description="종목코드 6자리", examples=["005930"])
    limit: int = Field(..., description="요청한 최대 건수", examples=[5])
    count: int = Field(..., description="실제 반환 건수", examples=[3])
    items: list[FinanceNewsItem] = Field(
        default_factory=list,
        description="정제된 뉴스/리포트 목록",
    )
    fetched_at: datetime = Field(..., description="조회 시각 (UTC)")
    message: str | None = Field(None, description="부가 메시지")
