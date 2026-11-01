"""The code of a step: its `step.py`, or the built-in runner of a step without code (spec/extensibility.md)."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from collections.abc import Callable
from pathlib import Path

from q3tui.engine.ctx import Ctx, StepError
from q3tui.flowdef.model import Instance


def import_file(path: Path, name: str):
    """Import a file of a step's folder; the folder's other modules can be imported by it."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


class LoadedStep:
    """A `step.py`: its class `Step`."""

    def __init__(self, inst: Instance, step):
        self.inst, self.step = inst, step

    async def run(self, ctx: Ctx) -> None:
        result = self.step.run(ctx)
        if inspect.isawaitable(result):
            await result

    def check(self, name: str, ctx: Ctx) -> bool | str:
        fn = getattr(self.step, f"check_{name}", None)
        if fn is None:
            return f"step.py has no check_{name}"
        return fn(ctx)

    def on_approve(self, ctx: Ctx) -> None:
        fn = getattr(self.step, "on_approve", None)
        if fn is not None:
            fn(ctx)

    def mcp_tools(self) -> dict[str, dict]:
        """name -> {description, params, method} of the methods marked with `@mcp_tool`."""
        out = {}
        for _, method in inspect.getmembers(self.step, predicate=callable):
            mark = getattr(method, "__q3tui_mcp__", None)
            if mark:
                out[mark["name"]] = {**mark, "method": method}
        return out


class BuiltinRunner:
    """A step without code: its tasks one after another (with `when` and `per_unit`), each result written to its
    `to` output. Nothing else."""

    def __init__(self, inst: Instance):
        self.inst = inst

    async def run(self, ctx: Ctx) -> None:
        for task in self.inst.tasks:
            if task.per_unit:
                if task.to:
                    raise StepError(f"task `{task.name}`: a `per_unit` task with `to` needs a step.py")
                for unit in ctx.units:
                    await ctx.task(task.name, unit=unit)
                continue
            result = await ctx.task(task.name)
            if task.to:
                target = ctx.outputs[task.to]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(result if isinstance(result, str) else json.dumps(result, indent=2) + "\n")

    def check(self, name: str, ctx: Ctx) -> bool | str:
        return f"`code {name}`: the step has no step.py"

    def on_approve(self, ctx: Ctx) -> None:
        return

    def mcp_tools(self) -> dict[str, dict]:
        return {}


class NotApproved:
    """A step.py of the project that you have not allowed: the step does not run."""

    def __init__(self, path: Path):
        self.path = path

    async def run(self, ctx: Ctx) -> None:
        raise StepError(f"code not approved: {self.path} (allow it to run)")

    def check(self, name: str, ctx: Ctx) -> bool | str:
        return "code not approved"

    def on_approve(self, ctx: Ctx) -> None:
        return

    def mcp_tools(self) -> dict[str, dict]:
        return {}


class CodeLoader:
    """`code_for(inst)` of the engine. A file under `<project>/.q3tui/` runs only once `approved(path, content)`."""

    def __init__(self, project_q3: Path | None, approved: Callable[[Path, bytes], bool] | None = None):
        self.project_q3 = project_q3
        self.approved = approved
        self.cache: dict[str, tuple[bytes, object]] = {}

    def from_project(self, path: Path) -> bool:
        return self.project_q3 is not None and path.is_relative_to(self.project_q3)

    def __call__(self, inst: Instance):
        path = inst.folder / "step.py"
        if not path.is_file():
            return BuiltinRunner(inst)
        content = path.read_bytes()
        if self.from_project(path) and self.approved is not None and not self.approved(path, content):
            return NotApproved(path)
        cached = self.cache.get(inst.id)
        if cached and cached[0] == content:
            return cached[1]
        module = import_file(path, f"q3tui_steps.{inst.id}.step")
        cls = getattr(module, "Step", None)
        if cls is None:
            raise StepError(f"{path} has no class Step")
        code = LoadedStep(inst, cls())
        self.cache[inst.id] = (content, code)
        return code
