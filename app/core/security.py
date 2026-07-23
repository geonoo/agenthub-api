"""X-API-KEY authentication dependency and rate-limit / quota middleware."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.services import key_service

api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)

AUTH_EXEMPT_EXACT = {
    "/",
    "/favicon.ico",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/dashboard",
    "/api/v1/health",
    "/api/v1/auth/issue-key",
    "/api/v1/auth/send-code",
    "/api/v1/auth/verify-code",
    # MCP handshake / transport (must be public for Claude Desktop / mcp-remote)
    "/mcp",
    "/mcp/sse",
    "/mcp/messages",
    "/mcp/schema",
    "/mcp/tools",
    "/api/v1/mcp",
    "/api/v1/mcp/sse",
    "/api/v1/mcp/messages",
    "/api/v1/mcp/schema",
    "/api/v1/mcp/tools",
}
AUTH_EXEMPT_PREFIXES = (
    "/static",
    "/docs/",
    "/redoc/",
    "/mcp/",
    "/api/v1/mcp/",
)


def is_auth_exempt(path: str) -> bool:
    if path in AUTH_EXEMPT_EXACT:
        return True
    # Normalize trailing slash
    trimmed = path.rstrip("/") or "/"
    if trimmed in AUTH_EXEMPT_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)


def is_env_api_key(api_key: str | None, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not api_key:
        return False
    return api_key in settings.env_api_keys


def resolve_db_api_key(api_key: str | None):
    """Return ApiKey row if valid active DB key, else None."""
    if not api_key:
        return None
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        return key_service.find_active_key_by_raw(db, api_key)
    finally:
        db.close()


def is_valid_api_key(api_key: str | None, settings: Settings | None = None) -> bool:
    """Env master keys or active hashed DB keys."""
    if is_env_api_key(api_key, settings):
        return True
    return resolve_db_api_key(api_key) is not None


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate the X-API-KEY request header (env or DB)."""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-KEY 헤더가 필요합니다.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not is_valid_api_key(api_key, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 API 키입니다.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


class RateLimiter:
    """Simple sliding-window burst limiter (in-memory, per process)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False, 0
            bucket.append(now)
            return True, max(limit - len(bucket), 0)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


class APIKeyRateLimitMiddleware(BaseHTTPMiddleware):
    """Auth + daily quota (DB keys) + optional burst rate limit."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        settings = get_settings()
        path = request.url.path

        if request.method == "OPTIONS" or is_auth_exempt(path):
            # MCP / public routes: no auth, no DB, no quota accounting
            return await call_next(request)

        if not (path.startswith("/api/") or path.startswith("/mcp")):
            return await call_next(request)

        api_key = request.headers.get(settings.api_key_header) or request.headers.get(
            "x-api-key"
        )

        # 1) Env / MASTER keys — unlimited daily quota
        if is_env_api_key(api_key, settings):
            if settings.rate_limit_enabled:
                allowed, remaining = rate_limiter.allow(
                    key=f"env:{api_key}",
                    limit=settings.rate_limit_requests,
                    window_seconds=settings.rate_limit_window_seconds,
                )
                if not allowed:
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={
                            "detail": (
                                f"Rate limit exceeded: "
                                f"{settings.rate_limit_requests} req / "
                                f"{settings.rate_limit_window_seconds}s"
                            )
                        },
                        headers={
                            "Retry-After": str(settings.rate_limit_window_seconds),
                            "X-RateLimit-Limit": str(settings.rate_limit_requests),
                            "X-RateLimit-Remaining": "0",
                        },
                    )
                response = await call_next(request)
                response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_requests)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                return response
            return await call_next(request)

        # 2) DB hashed key validation
        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            row = key_service.find_active_key_by_raw(db, api_key) if api_key else None
            if not row:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={
                        "detail": "유효하지 않은 API 키이거나 X-API-KEY가 없습니다."
                    },
                    headers={"WWW-Authenticate": "ApiKey"},
                )

            # 3) Daily quota
            used = key_service.count_usage_today(db, row.id)
            if used >= row.daily_limit:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": (
                            f"Daily quota exceeded: {used}/{row.daily_limit} "
                            f"(Free Tier). Tomorrow UTC 00:00에 리셋됩니다."
                        ),
                        "daily_limit": row.daily_limit,
                        "used_today": used,
                        "remaining_today": 0,
                    },
                    headers={
                        "Retry-After": "86400",
                        "X-RateLimit-Limit": str(row.daily_limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )

            # Burst window (optional)
            if settings.rate_limit_enabled:
                allowed, _burst_remaining = rate_limiter.allow(
                    key=f"db:{row.id}",
                    limit=settings.rate_limit_requests,
                    window_seconds=settings.rate_limit_window_seconds,
                )
                if not allowed:
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={
                            "detail": (
                                f"Rate limit exceeded: "
                                f"{settings.rate_limit_requests} req / "
                                f"{settings.rate_limit_window_seconds}s"
                            )
                        },
                        headers={
                            "Retry-After": str(settings.rate_limit_window_seconds),
                        },
                    )

            response = await call_next(request)

            # 4) Record usage after response
            try:
                key_service.record_usage(
                    db,
                    api_key_id=row.id,
                    endpoint=f"{request.method} {path}",
                    status_code=response.status_code,
                )
            except Exception:  # noqa: BLE001
                db.rollback()

            remaining_today = max(row.daily_limit - (used + 1), 0)
            response.headers["X-RateLimit-Limit"] = str(row.daily_limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining_today)
            return response
        finally:
            db.close()
