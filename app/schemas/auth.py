"""Auth / API key schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class IssueKeyRequest(BaseModel):
    email: EmailStr = Field(..., description="발급받을 이메일 주소", examples=["user@example.com"])


class IssueKeyResponse(BaseModel):
    email: str = Field(..., description="등록된 이메일")
    api_key: str = Field(
        ...,
        description="원본 API Key (이 응답에서만 1회 표시). X-API-KEY 헤더에 사용하세요.",
    )
    key_prefix: str = Field(..., description="키 앞부분 (식별용)")
    daily_limit: int = Field(..., description="Free Tier 일일 호출 한도", examples=[1000])
    created_at: datetime
    message: str = Field(
        default="API Key는 지금 한 번만 보여집니다. 안전한 곳에 복사해 두세요.",
    )


class UsageResponse(BaseModel):
    key_prefix: str
    plan: str = Field(..., examples=["free"])
    daily_limit: int
    used_today: int
    remaining_today: int
    used_month: int
    is_active: bool
