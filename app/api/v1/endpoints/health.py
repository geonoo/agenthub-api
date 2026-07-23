"""Health check endpoint."""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="서비스 헬스 체크",
    description="API 서버 가용성 및 기본 상태를 확인합니다. 인증이 필요하지 않습니다.",
)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="AgentHub API Service",
        timestamp=datetime.now(timezone.utc),
    )
