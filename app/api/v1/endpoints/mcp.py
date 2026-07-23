"""MCP HTTP+SSE transport (legacy) + JSON-RPC helpers.

SSE transport contract (mcp-remote / Claude Desktop):
1. Client GET /mcp/sse  → long-lived SSE stream
2. Server sends `event: endpoint` with `/mcp/messages?session_id=...`
3. Client POST JSON-RPC to that URL
4. Server returns HTTP 202; actual JSON-RPC *result* is pushed on the SSE
   stream as `event: message` (session-correlated)

Direct POST /mcp still returns JSON in the HTTP body for simple clients/tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.dart_service import DartService, get_dart_service
from app.services.finance_service import FinanceService, get_finance_service

logger = logging.getLogger(__name__)

router = APIRouter()

SERVER_INFO = {
    "name": "agenthub",
    "version": "0.1.0",
}

PROTOCOL_VERSION = "2024-11-05"

# Session TTL / cleanup
_SESSION_TTL_SECONDS = 600

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


@dataclass
class SseSession:
    session_id: str
    queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    created_at: float = field(default_factory=time.monotonic)


class SseSessionHub:
    """In-memory session registry linking POST /messages → GET /sse stream."""

    def __init__(self) -> None:
        self._sessions: dict[str, SseSession] = {}
        self._lock = asyncio.Lock()

    async def create(self) -> SseSession:
        await self._cleanup_expired()
        session_id = secrets.token_urlsafe(16)
        session = SseSession(session_id=session_id)
        async with self._lock:
            self._sessions[session_id] = session
        logger.info("MCP SSE session created: %s", session_id)
        return session

    async def get(self, session_id: str) -> SseSession | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def publish(self, session_id: str, payload: dict[str, Any]) -> bool:
        session = await self.get(session_id)
        if not session:
            return False
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        await session.queue.put(f"event: message\ndata: {data}\n\n")
        return True

    async def close(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            await session.queue.put(None)
            logger.info("MCP SSE session closed: %s", session_id)

    async def _cleanup_expired(self) -> None:
        now = time.monotonic()
        async with self._lock:
            expired = [
                sid
                for sid, s in self._sessions.items()
                if now - s.created_at > _SESSION_TTL_SECONDS
            ]
            for sid in expired:
                self._sessions.pop(sid, None)


sse_hub = SseSessionHub()


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

    if method in {"initialize", "mcp/initialize"}:
        return _initialize_result()

    if method in {
        "notifications/initialized",
        "initialized",
        "notifications/cancelled",
    }:
        return None  # notification — no result body

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


_HANDSHAKE_METHODS = {
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


async def process_jsonrpc_dict(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Process one JSON-RPC object. Returns response dict, or None for notifications."""
    req_id = payload.get("id")
    method = str(payload.get("method") or "")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    is_notification = "id" not in payload or payload.get("id") is None

    # Pure notifications without method responses
    if method.startswith("notifications/") or method in {"initialized"}:
        if is_notification or req_id is None:
            await handle_mcp_method(method, params)
            return None

    try:
        if method in _HANDSHAKE_METHODS and method not in {
            "tools/call",
            "mcp/tools/call",
        }:
            result = await handle_mcp_method(method, params)
            if result is None or (
                is_notification and method.startswith("notifications/")
            ):
                return None
            return _rpc_result(req_id, result)

        dart_service = get_dart_service()
        finance_service = get_finance_service()
        result = await handle_mcp_method(
            method, params, dart_service, finance_service
        )
        if result is None:
            return None
        return _rpc_result(req_id, result)
    except Exception as exc:  # noqa: BLE001
        if is_notification:
            logger.warning("MCP notification error (%s): %s", method, exc)
            return None
        return _rpc_error(req_id, -32000, str(exc))


async def _dispatch_jsonrpc_http(payload: JsonRpcRequest) -> JSONResponse:
    """Direct HTTP JSON response (non-SSE clients / tests)."""
    raw = payload.model_dump()
    response = await process_jsonrpc_dict(raw)
    if response is None:
        return JSONResponse({"jsonrpc": "2.0", "result": {}}, status_code=200)
    return JSONResponse(response)


@router.post(
    "",
    summary="MCP JSON-RPC endpoint (direct HTTP)",
    description="Returns JSON-RPC result in the HTTP body. Prefer SSE for Claude Desktop.",
)
async def mcp_jsonrpc(payload: JsonRpcRequest) -> JSONResponse:
    return await _dispatch_jsonrpc_http(payload)


@router.post(
    "/messages",
    summary="MCP SSE message endpoint",
    description=(
        "Client→server JSON-RPC sink for SSE transport. "
        "Requires session_id query param from the SSE `endpoint` event. "
        "Returns 202; JSON-RPC responses are delivered on the SSE stream."
    ),
)
async def mcp_messages(request: Request) -> Response:
    session_id = (
        request.query_params.get("session_id")
        or request.query_params.get("sessionId")
        or ""
    ).strip()
    if not session_id:
        return JSONResponse(
            {"detail": "session_id query parameter is required"},
            status_code=400,
        )

    session = await sse_hub.get(session_id)
    if not session:
        return JSONResponse(
            {"detail": f"Unknown or expired SSE session: {session_id}"},
            status_code=404,
        )

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)

    # Support single object or batch array
    messages = body if isinstance(body, list) else [body]
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        method = msg.get("method", "")
        logger.info(
            "MCP SSE message session=%s method=%s id=%s",
            session_id,
            method,
            msg.get("id"),
        )
        rpc_response = await process_jsonrpc_dict(msg)
        if rpc_response is not None:
            ok = await sse_hub.publish(session_id, rpc_response)
            if not ok:
                return JSONResponse(
                    {"detail": "SSE session gone"},
                    status_code=404,
                )

    # Spec: accept POST; deliver results via SSE
    return Response(status_code=202)


@router.get(
    "/tools",
    summary="List MCP tools",
)
async def list_mcp_tools() -> dict[str, Any]:
    return {"tools": TOOLS, "server": SERVER_INFO}


@router.get(
    "/schema",
    summary="MCP tools JSON schema",
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
        "Opens an SSE stream, creates a session, and emits `endpoint` with "
        "`/mcp/messages?session_id=...`. Subsequent JSON-RPC responses are "
        "pushed as `event: message` on this stream."
    ),
)
async def mcp_sse(request: Request) -> StreamingResponse:
    base = request.url.path.rsplit("/sse", 1)[0] or "/mcp"
    session = await sse_hub.create()
    messages_path = f"{base}/messages?session_id={session.session_id}"

    async def event_stream():
        # 1) Mandatory first event — tells client where to POST
        yield f"event: endpoint\ndata: {messages_path}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(session.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # keep-alive comment
                    yield ": ping\n\n"
                    continue
                if item is None:
                    break
                yield item
        except asyncio.CancelledError:
            return
        finally:
            await sse_hub.close(session.session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
