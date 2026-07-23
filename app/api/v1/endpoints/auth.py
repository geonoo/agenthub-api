"""API Key self-service issuance, email verification, and usage endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import (
    IssueKeyRequest,
    IssueKeyResponse,
    SendCodeRequest,
    SendCodeResponse,
    UsageResponse,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from app.services import email_service, key_service

router = APIRouter()
api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)


@router.post(
    "/send-code",
    response_model=SendCodeResponse,
    summary="Send email verification code",
    description="Generate a 6-digit code, store it for 5 minutes, and email via Resend.",
)
def send_code(
    body: SendCodeRequest,
    db: Session = Depends(get_db),
) -> SendCodeResponse:
    settings = get_settings()
    row = email_service.create_verification(db, str(body.email))
    email_service.send_verification_email(row.email, row.code)
    return SendCodeResponse(
        email=row.email,
        expires_in_seconds=settings.email_code_ttl_minutes * 60,
    )


@router.post(
    "/verify-code",
    response_model=VerifyCodeResponse,
    summary="Verify email code",
    description="Validate the 6-digit code before API key issuance.",
)
def verify_code(
    body: VerifyCodeRequest,
    db: Session = Depends(get_db),
) -> VerifyCodeResponse:
    row = email_service.verify_code(db, str(body.email), body.code)
    return VerifyCodeResponse(email=row.email, verified=True)


@router.post(
    "/issue-key",
    response_model=IssueKeyResponse,
    summary="Issue a new AgentHub API Key",
    description=(
        "Issue a Free-tier API key only after the email has been verified via /verify-code. "
        "The raw key is returned only once; store it securely."
    ),
)
def issue_key(
    body: IssueKeyRequest,
    db: Session = Depends(get_db),
) -> IssueKeyResponse:
    email_service.require_verified_email(db, str(body.email))
    raw, row, user = key_service.issue_api_key(db, str(body.email))
    email_service.consume_verification(db, user.email)
    return IssueKeyResponse(
        email=user.email,
        api_key=raw,
        key_prefix=row.key_prefix,
        daily_limit=row.daily_limit,
        created_at=row.created_at,
    )


@router.get(
    "/usage",
    response_model=UsageResponse,
    summary="Get today's API usage for the current key",
    description="Requires X-API-KEY. Returns daily quota usage and remaining calls.",
)
def get_usage(
    api_key: str | None = Security(api_key_header),
    db: Session = Depends(get_db),
) -> UsageResponse:
    settings = get_settings()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-KEY 헤더가 필요합니다.",
        )

    if api_key in settings.env_api_keys:
        return UsageResponse(
            key_prefix=api_key[:12],
            plan="master",
            daily_limit=-1,
            used_today=0,
            remaining_today=-1,
            used_month=0,
            is_active=True,
        )

    row = key_service.find_active_key_by_raw(db, api_key)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 API 키입니다.",
        )
    snap = key_service.usage_snapshot(db, row)
    return UsageResponse(**snap)
