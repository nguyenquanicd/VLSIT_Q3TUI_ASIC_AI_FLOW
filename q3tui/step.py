"""What a step's `step.py` imports from Q3TUI (spec/extensibility.md "`step.py`")."""

from __future__ import annotations

from q3tui.engine.ctx import StepError


def mcp_tool(name: str, description: str, params: dict | None = None):
    """Mark a method of `Step` as an MCP tool of the step (LLM runtime "MCP tools"); STEP.md lists it in `mcp_tools`.
    `params`: the name and type of each argument (`{"module": str}`); the method gets them as `args`."""

    def mark(fn):
        fn.__q3tui_mcp__ = {"name": name, "description": description, "params": params or {}}
        return fn

    return mark


__all__ = ["StepError", "mcp_tool"]
