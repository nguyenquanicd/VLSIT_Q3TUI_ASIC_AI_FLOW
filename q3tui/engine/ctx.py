"""`ctx`: the narrow API of a running step (spec/extensibility.md "`ctx`"). It has no engine, no state, no
config, and no path the step did not declare."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from q3tui.flowdef.model import Instance


class StepError(Exception):
    """An error of the step itself (it asked a kind it does not declare, …): the step fails."""


@dataclass
class Changes:
    """What changed since the step last ran (spec/engine.md "Staleness and updates")."""

    first_run: bool = True
    inputs: list[dict] = field(default_factory=list)  # {artifact, change: added | changed | removed}
    params: list[dict] = field(default_factory=list)  # {name, old, new}
    requests: list[dict] = field(default_factory=list)  # {source, text, unit, kind, key}
    definition_changed: list[str] = field(default_factory=list)
    edited_outputs: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "first_run": self.first_run,
            "inputs": [f"{c['artifact']} {c['change']}" for c in self.inputs],
            "params": [c["name"] for c in self.params],
            "requests": [f"[{r['source']}] {r['text'][:80]}" for r in self.requests],
            "definition_changed": self.definition_changed,
            "edited_outputs": self.edited_outputs,
        }

    @property
    def any(self) -> bool:
        return bool(self.first_run or self.inputs or self.params or self.requests or self.definition_changed
                    or self.edited_outputs)


@dataclass
class Asked:
    kind: str
    key: str
    text: str
    default: Any
    options: list[dict]
    blocking: bool


@dataclass
class Problem:
    kind: str
    unit: str
    key: str
    text: str

    @property
    def ident(self) -> list[str]:
        return [self.kind, str(self.unit), str(self.key)]


class Services(Protocol):
    """What runs the LLM tasks and the tools of a step (LLM runtime, Tools / EDA)."""

    async def task(self, ctx: Ctx, name: str, unit: str | None, vars: dict) -> Any: ...

    async def tool(self, ctx: Ctx, role: str, log: str | None, timeout: str, vars: dict) -> Any: ...


class NoServices:
    async def task(self, ctx, name, unit, vars):
        raise StepError(f"task `{name}`: no LLM runtime in this engine")

    async def tool(self, ctx, role, log, timeout, vars):
        raise StepError(f"tool `{role}`: no tool runner in this engine")


class Ctx:
    def __init__(self, inst: Instance, *, params: dict, inputs: dict[str, list[Path]], assets: dict[str, Path],
                 packages: dict[str, Path], outputs: dict[str, Path], units: list[str], changes: Changes,
                 settled: list[dict], services: Services, settled_keys: dict[str, str | None],
                 emit: Callable[[str, str], None], root: Path, work: Path):
        self.params = params
        self.inputs = inputs
        self.assets = assets
        self.packages = packages
        self.outputs = outputs
        self.units = units
        self.changes = changes
        self.settled = settled
        self._inst = inst
        self._services = services
        self._settled_keys = settled_keys
        self._emit = emit
        self._root = root
        self._work = work
        self._asked: list[Asked] = []
        self._problems: list[Problem] = []
        self._tools: dict[str, dict] = {}

    # -- what the step does -------------------------------------------------------------------

    async def task(self, name: str, unit: str | None = None, **vars) -> Any:
        if name not in {t.name for t in self._inst.tasks}:
            raise StepError(f"task `{name}` is not declared in STEP.md (or its `when` is false)")
        return await self._services.task(self, name, unit, vars)

    async def tool(self, role: str, log: str | None = None, timeout: str = "broken", **vars) -> Any:
        if role not in {t["role"] for t in self._inst.tools}:
            raise StepError(f"tool `{role}` is not declared in the step's `tools`")
        if timeout not in ("broken", "result"):
            raise StepError("`timeout` is `broken` or `result`")
        result = await self._services.tool(self, role, log, timeout, vars)
        self._tools[role] = {k: getattr(result, k, None) for k in ("ok", "returncode", "errors", "warnings",
                                                                   "timed_out", "na")}
        return result

    def ask(self, kind: str, key: str, text: str, default, options: list | None = None, blocking: bool = False):
        """Raise a question. A key already settled is not asked again: its answer is returned."""
        if kind != "design_choice" and kind not in self._inst.questions:
            raise StepError(f"question kind `{kind}` is not in the step's `questions`")
        if not key:
            raise StepError("a question needs a `key`")
        opts = [o if isinstance(o, dict) else {"text": str(o)} for o in (options or [])]
        if len(opts) > 4:
            raise StepError("a question has at most 4 options")
        if key in self._settled_keys:
            return self._settled_keys[key]
        if any(a.key == key for a in self._asked):
            return None
        self._asked.append(Asked(kind, key, text, default, opts, bool(blocking)))
        return None

    def handback(self, kind: str, unit, key, text: str) -> None:
        if kind not in self._inst.handback:
            raise StepError(f"problem kind `{kind}` is not in the step's `handback`")
        self._problems.append(Problem(kind, str(unit), str(key), text))

    def log(self, message: str) -> None:
        self._emit("log", message)

    def warn(self, message: str) -> None:
        self._emit("warning", message)
