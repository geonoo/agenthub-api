"""Lightweight MCP (Model Context Protocol) HTTP/JSON-RPC interface."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.security import verify_api_key
from app.services.dart_service import DartService, get_dart_service
from app.services.finance_service import FinanceService, get_finance_service

router = APIRouter()

SERVER_INFO = {
    "name": "agenthub",
    "version": "0.1.0",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_dart_disclosures",
        "description": (
            "Fetch clean, token-optimized Korean DART corporate filings "
            "(Markdown + structured metrics) for a 6-digit stock code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "pattern": "^\\d{6}$",
                    "description": "Korean stock code, e.g. 005930",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Max number of recent filings",
                },
            },
            "required": ["stock_code"],
        },
    },
    {
        "name": "get_stock_news",
        "description": (
            "Fetch clean, token-optimized Korean stock news/reports from Naver Finance "
            "as Markdown for LLM agents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "pattern": "^\\d{6}$",
                    "description": "Korean stock code, e.g. 005930",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Max number of news items",
                },
            },
            "required": ["stock_code"],
        },
    },
]


class JsonRpcRequest(BaseModel):
    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    id: str | int | None = Field(None, description="Request id")
    method: str = Field(..., description="MCP / JSON-RPC method name")
    params: dict[str, Any] | None = Field(default=None, description="Method params")


def _rpc_result(req_id: str | int | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(
    req_id: str | int | None,
    code: int,
    message: str,
    data: Any = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


async def _call_tool(
    name: str,
    arguments: dict[str, Any],
    dart_service: DartService,
    finance_service: FinanceService,
) -> dict[str, Any]:
    if name == "get_dart_disclosures":
        stock_code = str(arguments.get("stock_code", "")).strip()
        limit = int(arguments.get("limit") or 5)
        data = await dart_service.get_company_disclosures(
            stock_code=stock_code,
            limit=limit,
        )
        text = data.model_dump_json()
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": data.model_dump(mode="json"),
            "isError": False,
        }

    if name == "get_stock_news":
        stock_code = str(arguments.get("stock_code", "")).strip()
        limit = int(arguments.get("limit") or 5)
        data = await finance_service.get_stock_news(stock_code=stock_code, limit=limit)
        text = data.model_dump_json()
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": data.model_dump(mode="json"),
            "isError": False,
        }

    return {
        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        "isError": True,
    }


async def handle_mcp_method(
    method: str,
    params: dict[str, Any] | None,
    dart_service: DartService,
    finance_service: FinanceService,
) -> Any:
    params = params or {}

    if method in {"initialize", "mcp/initialize"}:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        }

    if method in {"tools/list", "mcp/tools/list"}:
        return {"tools": TOOLS}

    if method in {"tools/call", "mcp/tools/call"}:
        name = params.get("name") or params.get("tool")
        arguments = params.get("arguments") or params.get("args") or {}
        if not name:
            raise ValueError("tool name is required")
        return await _call_tool(name, arguments, dart_service, finance_service)

    if method in {"ping", "mcp/ping"}:
        return {}

    raise ValueError(f"Unsupported method: {method}")


@router.post(
    "",
    summary="MCP JSON-RPC endpoint",
    description=(
        "Model Context Protocol compatible JSON-RPC endpoint for Claude Desktop "
        "and other MCP clients. Tools: get_dart_disclosures, get_stock_news. "
        "Requires X-API-KEY."
    ),
    include_in_schema=True,
    dependencies=[Depends(verify_api_key)],
)
async def mcp_jsonrpc(
    payload: JsonRpcRequest,
    dart_service: DartService = Depends(get_dart_service),
    finance_service: FinanceService = Depends(get_finance_service),
) -> JSONResponse:
    try:
        result = await handle_mcp_method(
            payload.method,
            payload.params,
            dart_service,
            finance_service,
        )
        return JSONResponse(_rpc_result(payload.id, result))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            _rpc_error(payload.id, -32000, str(exc)),
            status_code=200,
        )


@router.get(
    "/tools",
    summary="List MCP tools",
    description="Convenience REST view of MCP tools (same catalog as tools/list).",
    dependencies=[Depends(verify_api_key)],
)
async def list_mcp_tools() -> dict[str, Any]:
    return {"tools": TOOLS, "server": SERVER_INFO}


@router.get(
    "/sse",
    summary="MCP SSE handshake (minimal)",
    description=(
        "Minimal Server-Sent Events stream for MCP-compatible clients. "
        "Sends an endpoint event pointing to POST /mcp for JSON-RPC messages."
    ),
    dependencies=[Depends(verify_api_key)],
)
async def mcp_sse(request: Request) -> StreamingResponse:
    async def event_stream():
        # MCP SSE transport typically announces the message endpoint first
        yield "event: endpoint\ndata: /mcp\n\n"
        # Keep-alive comments; client drives tools via POST /mcp
        while True:
            if await request.is_disconnected():
                break
            yield ": ping\n\n"
            # Avoid tight loop — Starlette will interleave; use tiny sleep via yield pattern
            import asyncio

            await asyncio.sleep(15)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


