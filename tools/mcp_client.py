"""Client for the bank-ops MCP server, behind a timeout and circuit breaker."""

from __future__ import annotations

import json
from typing import Any

from mcp.client.client import Client

from core.config import get_settings
from core.resilience import breakers, check_fault, with_timeout

# Tests point this at the in-process server object instead of a URL.
_target: Any = None


def set_target(target: Any) -> None:
    global _target
    _target = target


class MCPToolError(RuntimeError):
    pass


async def call_mcp(tool: str, arguments: dict) -> dict:
    check_fault("mcp")
    target = _target or get_settings().mcp_server_url

    async def _call() -> dict:
        async with Client(target, read_timeout_seconds=get_settings().tool_timeout_s) as client:
            result = await client.call_tool(tool, arguments)
        if result.is_error:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            raise MCPToolError(text or f"MCP tool {tool} failed")
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        return json.loads(result.content[0].text)

    return await breakers["mcp"].call(lambda: with_timeout(_call()))
