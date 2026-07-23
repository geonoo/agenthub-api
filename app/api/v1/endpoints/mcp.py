"""Lightweight MCP (Model Context Protocol) HTTP/JSON-RPC + SSE interface.

Handshake paths are auth-exempt (see security middleware) so Claude Desktop /
mcp-remote can complete `initialize` without blocking on API-key or SQLite.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.dart_service import DartService, get_dart_service
from app.services.finance_service import FinanceService, get_finance_service

router = APIRouter()

SERVER_INFO = {
    "name": "agenthub",
    "version": "0.1.0",
}

PROTOCOL_VERSION = "2024-11-05"

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


def _initialize_result() -> dict[str, Any]:
    """Pure in-memory handshake payload — no DB / no I/O."""
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": SERVER_INFO,
    }


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
    dart_service: DartService | None = None,
    finance_service: FinanceService | None = None,
) -> Any:
    params = params or {}

    # Handshake / discovery — never touch DB or upstream services
    if method in {"initialize", "mcp/initialize"}:
        return _initialize_result()

    if method in {
        "notifications/initialized",
        "initialized",
        "notifications/cancelled",
    }:
        return {}

    if method in {"ping", "mcp/ping"}:
        return {}

    if method in {"tools/list", "mcp/tools/list"}:
        return {"tools": TOOLS}

    if method in {"tools/call", "mcp/tools/call"}:
        if dart_service is None or finance_service is None:
            raise ValueError("tool services unavailable")
        name = params.get("name") or params.get("tool")
        arguments = params.get("arguments") or params.get("args") or {}
        if not name:
            raise ValueError("tool name is required")
        return await _call_tool(name, arguments, dart_service, finance_service)

    raise ValueError(f"Unsupported method: {method}")


async def _dispatch_jsonrpc(payload: JsonRpcRequest) -> JSONResponse:
    """Route JSON-RPC; skip service DI for handshake methods."""
    method = payload.method
    is_handshake = method in {
        "initialize",
        "mcp/initialize",
        "notifications/initialized",
        "initialized",
        "notifications/cancelled",
        "ping",
        "mcp/ping",
        "tools/list",
        "mcp/tools/list",
    }

    try:
        if is_handshake:
            result = await handle_mcp_method(method, payload.params)
            # notifications may have id=null — still return 202-style empty OK
            if payload.id is None and method.startswith("notifications/"):
                return JSONResponse({"jsonrpc": "2.0", "result": result})
            return JSONResponse(_rpc_result(payload.id, result))

        dart_service = get_dart_service()
        finance_service = get_finance_service()
        result = await handle_mcp_method(
            method,
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


@router.post(
    "",
    summary="MCP JSON-RPC endpoint",
    description=(
        "MCP JSON-RPC endpoint (initialize / tools/list / tools/call). "
        "Auth-exempt for Claude Desktop handshake; optional X-API-KEY still accepted."
    ),
    include_in_schema=True,
)
async def mcp_jsonrpc(payload: JsonRpcRequest) -> JSONResponse:
    return await _dispatch_jsonrpc(payload)


@router.post(
    "/messages",
    summary="MCP SSE message endpoint",
    description="JSON-RPC message sink used by MCP SSE transport (mcp-remote).",
    include_in_schema=True,
)
async def mcp_messages(payload: JsonRpcRequest) -> JSONResponse:
    return await _dispatch_jsonrpc(payload)


@router.get(
    "/tools",
    summary="List MCP tools",
    description="Convenience REST view of MCP tools (same catalog as tools/list).",
)
async def list_mcp_tools() -> dict[str, Any]:
    return {"tools": TOOLS, "server": SERVER_INFO}


@router.get(
    "/schema",
    summary="MCP tools JSON schema",
    description="Tool input schemas for MCP / agent discovery.",
)
async def mcp_schema() -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": SERVER_INFO,
        "tools": TOOLS,
    }


@router.get(
    "/sse",
    summary="MCP SSE handshake",
    description=(
        "Server-Sent Events stream for MCP clients. Immediately emits an "
        "`endpoint` event pointing at POST /mcp/messages (no DB, no auth)."
    ),
)
async def mcp_sse(request: Request) -> StreamingResponse:
    # Prefer absolute path under the same mount prefix the client used
    base = request.url.path.rsplit("/sse", 1)[0] or "/mcp"
    messages_path = f"{base}/messages"

    async def event_stream():
        # First event must be immediate for mcp-remote handshake
        yield f"event: endpoint\ndata: {messages_path}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(1)
                yield ": ping\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
