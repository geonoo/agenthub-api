"""API Key self-service issuance and usage endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import IssueKeyRequest, IssueKeyResponse, UsageResponse
from app.services import key_service

router = APIRouter()
api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)


@router.post(
    "/issue-key",
    response_model=IssueKeyResponse,
    summary="Issue a new AgentHub API Key",
    description=(
        "Create a Free-tier API key for the given email. "
        "The raw key is returned only once; store it securely."
    ),
)
def issue_key(
    body: IssueKeyRequest,
    db: Session = Depends(get_db),
) -> IssueKeyResponse:
    raw, row, user = key_service.issue_api_key(db, str(body.email))
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
        # Env/master keys: unlimited
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
