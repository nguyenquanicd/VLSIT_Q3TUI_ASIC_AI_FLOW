"""What runs a step's LLM tasks and tools for the engine (`ctx.task`, `ctx.tool`)."""

from __future__ import annotations

from typing import Any

from q3tui.engine.ctx import Ctx
from q3tui.llm.runtime import LLMRuntime
from q3tui.tools.run import ToolRunner


class StepServices:
    def __init__(self, llm: LLMRuntime, tools: ToolRunner):
        self.llm, self.tools = llm, tools

    async def task(self, ctx: Ctx, name: str, unit: str | None, vars: dict) -> Any:
        return await self.llm.task(ctx, name, unit, vars)

    async def tool(self, ctx: Ctx, role: str, log: str | None, timeout: str, vars: dict) -> Any:
        decl = next(t for t in ctx._instance.tools if t["role"] == role)
        return await self.tools.run(ctx._instance.id, role, required=decl["required"], log=log, timeout=timeout,
                                    vars=vars)

    def step_started(self, ctx: Ctx) -> None:
        self.llm.step_started(ctx)

    def step_finished(self, ctx: Ctx, result: str) -> None:
        self.llm.step_finished(ctx, result)
