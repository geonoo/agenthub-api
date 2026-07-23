"""Auth / API key schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class SendCodeRequest(BaseModel):
    email: EmailStr = Field(..., description="인증 메일을 받을 주소", examples=["user@example.com"])


class SendCodeResponse(BaseModel):
    email: str
    message: str = "인증번호를 이메일로 발송했습니다. 5분 내에 입력해 주세요."
    expires_in_seconds: int = 300


class VerifyCodeRequest(BaseModel):
    email: EmailStr = Field(..., description="인증할 이메일")
    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="6자리 숫자 인증번호",
        examples=["123456"],
    )


class VerifyCodeResponse(BaseModel):
    email: str
    verified: bool = True
    message: str = "이메일 인증이 완료되었습니다. API Key를 발급받을 수 있습니다."


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
