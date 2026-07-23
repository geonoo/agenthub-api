"""X-API-KEY authentication dependency and rate-limit middleware."""

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

api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)

# Paths that skip API-key auth (prefix match for /static)
AUTH_EXEMPT_EXACT = {
    "/",
    "/favicon.ico",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/health",
}
AUTH_EXEMPT_PREFIXES = (
    "/static",
    "/docs/",
    "/redoc/",
)


def is_auth_exempt(path: str) -> bool:
    if path in AUTH_EXEMPT_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)


def is_valid_api_key(api_key: str | None, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not api_key:
        return False
    return api_key in settings.valid_api_keys


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate the X-API-KEY request header.

    Raises:
        HTTPException: 401 if missing or invalid.
    """
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
    """Simple sliding-window rate limiter (in-memory, per process)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Return (allowed, remaining)."""
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
    """Enforce X-API-KEY on protected routes and apply per-key rate limits."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        settings = get_settings()
        path = request.url.path

        if request.method == "OPTIONS" or is_auth_exempt(path):
            return await call_next(request)

        # Only gate API / MCP surfaces via middleware; static already exempt
        if not (
            path.startswith("/api/")
            or path.startswith("/mcp")
        ):
            return await call_next(request)

        api_key = request.headers.get(settings.api_key_header) or request.headers.get(
            "x-api-key"
        )
        if not is_valid_api_key(api_key, settings):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "유효하지 않은 API 키이거나 X-API-KEY가 없습니다."},
                headers={"WWW-Authenticate": "ApiKey"},
            )

        if settings.rate_limit_enabled:
            allowed, remaining = rate_limiter.allow(
                key=api_key or request.client.host if request.client else "unknown",
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
