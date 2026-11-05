"""The Q3TUI tools (`mcp__q3tui__*`) for a Codex run: a minimal MCP server (streamable HTTP, JSON responses) in this process.

The tools are closures over the engine's live state (the parsed design, the ops of the TUI, the role's notes), so they cannot
move to a separate process like a stdio server would. Codex is told the endpoint with `-c mcp_servers.q3tui.url=…` and the
bearer token through the environment. Only what Codex uses is implemented: initialize, tools/list, tools/call, ping.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

from q3tui.llm.tooldef import json_schema

SERVER_NAME = "q3tui"
TOKEN_ENV = "Q3TUI_MCP_TOKEN"
PROTOCOL = "2025-06-18"
MAX_BODY = 8 * 1024 * 1024


class ToolBridge:
    """`async with ToolBridge(tools) as bridge:` → bridge.url / bridge.token while it is open."""

    def __init__(self, tools: list[Any], emit=None, stage: str = ""):
        self.tools = {t.name: t for t in tools}
        self.token = secrets.token_urlsafe(24)
        self.url = ""
        self._server: asyncio.AbstractServer | None = None
        self._emit, self._stage = emit, stage

    async def __aenter__(self) -> "ToolBridge":
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self._server.sockets[0].getsockname()[1]}/mcp"
        return self

    async def __aexit__(self, *exc) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    # -- HTTP ---------------------------------------------------------------------------------------------------

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode("latin-1").split("\r\n")
                method = lines[0].split(" ", 1)[0]
                headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:] if ":" in l)}
                length = int(headers.get("content-length") or 0)
                if length > MAX_BODY:
                    await self._send(writer, 413, b"")
                    break
                body = await reader.readexactly(length) if length else b""
                if headers.get("authorization") != f"Bearer {self.token}":
                    await self._send(writer, 401, b"")
                elif method != "POST":  # (no server-initiated stream: allowed by the transport)
                    await self._send(writer, 405, b"")
                else:
                    reply = await self._rpc(body)
                    await (self._send(writer, 202, b"") if reply is None else
                           self._send(writer, 200, json.dumps(reply).encode(), "application/json"))
                if headers.get("connection", "").lower() == "close":
                    break
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.LimitOverrunError):
            pass
        finally:
            writer.close()

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, status: int, body: bytes, ctype: str = "text/plain") -> None:
        reason = {200: "OK", 202: "Accepted", 401: "Unauthorized", 405: "Method Not Allowed", 413: "Payload Too Large"}[status]
        writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
        await writer.drain()

    # -- JSON-RPC -------------------------------------------------------------------------------------------------

    async def _rpc(self, body: bytes) -> Any:
        try:
            msg = json.loads(body)
        except ValueError:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if isinstance(msg, list):  # a batch
            replies = [r for r in [await self._one(m) for m in msg] if r is not None]
            return replies or None
        return await self._one(msg)

    async def _one(self, msg: dict) -> dict | None:
        if "id" not in msg:  # a notification
            return None
        rid, method, params = msg["id"], msg.get("method"), msg.get("params") or {}

        def ok(result: dict) -> dict:
            return {"jsonrpc": "2.0", "id": rid, "result": result}

        if method == "initialize":
            return ok({"protocolVersion": params.get("protocolVersion") or PROTOCOL, "capabilities": {"tools": {}},
                       "serverInfo": {"name": SERVER_NAME, "version": "1"}})
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": [{"name": t.name, "description": t.description, "inputSchema": json_schema(t)}
                                 for t in self.tools.values()]})
        if method == "tools/call":
            t = self.tools.get(params.get("name"))
            if t is None:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
            try:
                out = await t.handler(params.get("arguments") or {})
            except Exception as exc:  # a tool that raises is an error result, not a dead run
                out = {"content": [{"type": "text", "text": f"error: {type(exc).__name__}: {exc}"}], "is_error": True}
            result = {"content": out.get("content", [])}
            if out.get("is_error"):
                result["isError"] = True
            return ok(result)
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
