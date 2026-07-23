"""DART corporate disclosure schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class StructuredMetric(BaseModel):
    """추출된 핵심 실적/재무 수치."""

    label: str = Field(..., description="지표명 (예: 매출액, 영업이익)", examples=["매출액"])
    value: str | None = Field(
        None,
        description="원문 수치 문자열 (단위 포함 가능)",
        examples=["279,604,799"],
    )
    unit: str | None = Field(None, description="단위 (예: 백만원, %)", examples=["백만원"])
    period: str | None = Field(
        None,
        description="해당 기간/열 헤더 (예: 당기, 2024.03)",
        examples=["당기"],
    )


class DisclosureItem(BaseModel):
    """정제된 개별 공시 항목."""

    rcept_no: str = Field(..., description="접수번호", examples=["20240515000123"])
    report_nm: str = Field(..., description="보고서명", examples=["분기보고서 (2024.03)"])
    rcept_dt: str = Field(..., description="접수일자 (YYYYMMDD)", examples=["20240515"])
    corp_code: str = Field(..., description="DART 고유번호", examples=["00126380"])
    corp_name: str = Field(..., description="회사명", examples=["삼성전자"])
    stock_code: str = Field(..., description="종목코드 (6자리)", examples=["005930"])
    flr_nm: str | None = Field(None, description="공시 제출인", examples=["삼성전자"])
    rm: str | None = Field(None, description="비고")
    viewer_url: str = Field(
        ...,
        description="DART 공시 뷰어 URL",
        examples=["https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240515000123"],
    )
    clean_markdown: str = Field(
        ...,
        description="HTML 노이즈를 제거한 Clean Markdown 본문 (토큰 최적화)",
    )
    structured_metrics: list[StructuredMetric] = Field(
        default_factory=list,
        description="본문에서 추출한 핵심 실적/재무 수치 JSON",
    )


class CompanyDisclosuresResponse(BaseModel):
    """종목 기준 최근 공시 정제 응답."""

    stock_code: str = Field(..., description="요청한 종목코드 (6자리)", examples=["005930"])
    corp_code: str = Field(..., description="매핑된 DART 고유번호", examples=["00126380"])
    corp_name: str | None = Field(None, description="회사명", examples=["삼성전자"])
    limit: int = Field(..., description="반환 공시 개수 상한", examples=[5])
    count: int = Field(..., description="실제 반환된 공시 개수", examples=[3])
    disclosures: list[DisclosureItem] = Field(
        default_factory=list,
        description="정제된 공시 목록",
    )
    fetched_at: datetime = Field(..., description="조회 시각 (UTC)")
    message: str | None = Field(
        None,
        description="부가 메시지 (부분 실패, 원문 미취득 등)",
    )
