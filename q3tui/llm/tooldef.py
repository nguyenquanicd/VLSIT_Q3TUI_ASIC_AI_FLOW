"""Backend-neutral definition of an in-process tool (`mcp__q3tui__*`).

The steps define their tools once with `@tool(name, description, schema)`; the Claude backend hands them to the Agent SDK
(`to_sdk`), the Codex backend serves them over a local MCP endpoint (`q3tui.llm.codex.bridge`). Same shape as the
SDK's `SdkMcpTool` (name, description, input_schema, handler), so `dataclasses.replace(tool, handler=…)` keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


@dataclass
class LlmTool:
    name: str
    description: str
    input_schema: Any  # {"field": str} shorthand, or a JSON Schema dict
    handler: Handler


def tool(name: str, description: str, input_schema: Any) -> Callable[[Handler], LlmTool]:
    def deco(fn: Handler) -> LlmTool:
        return LlmTool(name, description, input_schema, fn)

    return deco


def json_schema(t: Any) -> dict[str, Any]:
    """The tool's input as a JSON Schema object (the `{"field": type}` shorthand expanded)."""
    schema = t.input_schema
    if isinstance(schema, dict) and (schema.get("type") == "object" or "properties" in schema):
        return schema
    props = {k: {"type": _JSON_TYPES.get(v, "string")} for k, v in (schema or {}).items()} if isinstance(schema, dict) else {}
    return {"type": "object", "properties": props, "required": list(props)}


def to_sdk(t: Any):
    """The Agent SDK's tool for `t` (an SDK tool passes through)."""
    from claude_agent_sdk import SdkMcpTool

    if isinstance(t, SdkMcpTool):
        return t
    return SdkMcpTool(name=t.name, description=t.description, input_schema=t.input_schema, handler=t.handler)
