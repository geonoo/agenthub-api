"""AgentHub API Service — FastAPI application entrypoint."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.api.v1.endpoints import mcp as mcp_endpoint
from app.core.config import get_settings
from app.core.security import APIKeyRateLimitMiddleware
from app.db.session import init_db

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_application() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(APIKeyRateLimitMiddleware)

    application.include_router(api_router, prefix=settings.api_v1_prefix)
    application.include_router(mcp_endpoint.router, prefix="/mcp", tags=["MCP"])

    if STATIC_DIR.is_dir():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @application.get("/", include_in_schema=False)
    async def root() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/dashboard", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "dashboard.html")

    @application.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        favicon_path = STATIC_DIR / "favicon.ico"
        if favicon_path.is_file():
            return FileResponse(favicon_path)
        return Response(status_code=204)

    def custom_openapi():
        if application.openapi_schema:
            return application.openapi_schema

        openapi_schema = get_openapi(
            title=settings.app_name,
            version=settings.app_version,
            description=settings.app_description,
            routes=application.routes,
        )
        openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})[
            "ApiKeyAuth"
        ] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-KEY",
            "description": (
                "AgentHub API 키. 랜딩에서 발급받거나 MASTER_API_KEY를 사용하세요. "
                "health/docs/static/issue-key 제외."
            ),
        }
        openapi_schema["security"] = [{"ApiKeyAuth": []}]
        application.openapi_schema = openapi_schema
        return application.openapi_schema

    application.openapi = custom_openapi  # type: ignore[method-assign]
    return application


app = create_application()
