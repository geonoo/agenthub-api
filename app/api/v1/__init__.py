"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1.endpoints import health, stock

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(stock.router, prefix="/stock", tags=["Stock"])
