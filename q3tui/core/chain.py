"""The full unattended run (`q3tui auto`, TUI `/auto`): every flow of `pipeline.chain` (default spec → rtl → dv → sanity → fpga), in order,
without you — until each one has passed with the design as it is at the end (docs/spec/pipeline.md "Full unattended runs").

- A flow passes when its run completes with every step done. The Sanity flow (`LOOP_FLOWS`) runs through its fix loop (core/loop.py: analysis →
  hand-off → rtl → analysis) and passes when nothing is left open.
- A flow that changed the RTL (`src/rtl/`: the fixes Sanity's loop or fpga's ppa_optimize had the rtl flow make, dv's fix loop) makes every
  flow that checks the RTL (the flows after the design flow, `pipeline.design_flows`: dv, sanity, fpga) and passed with the RTL before run again,
  in the chain's order: a Sanity fix → dv again; an fpga PPA fix → dv and Sanity again. spec and rtl run once (the fixes went through rtl already).
- A flow whose run completes with only stale steps left (a late step changed what earlier ones were built from: fpga's post-PPA check formatted
  the RTL after the synthesis that passed) runs once more at once (`STALE_RERUNS`); a step that failed or waits stops it as before.
- Bounded: a flow runs at most `pipeline.chain_max_runs` times; a flow that does not pass stops the chain (yours to look at).
- A tool failure (a step's tool crashed, timed out, was missing or called wrongly — `failure.kind == "tool"`, not the design) goes at once to an LLM
  stage (`tool_fix`, told what the TUI's assistant is told: tui/failures.py — the error, the log, the tool's role, the step's options, the machine's
  memory and what the same tool needed in its earlier runs). It may change the tool's role (timeout_s, env, modules), a setting, or an option the
  flow's steps offer for it (`StepDef.tool_fix_options`, e.g. Sanity's `blackbox` for the memories that took RDC past the machine's memory), or
  change nothing (a crash of a busy machine); then the flow runs again. At most `TOOL_FIXES` per flow run; it never changes a tool's command, the
  RTL or the spec: what it cannot fix it says (the chain then stops).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

from q3tui import flows
from q3tui.core.project import Project

DEFAULT_CHAIN = ["spec", "rtl", "dv", "sanity", "fpga"]
STALE_RERUNS = 1  # a flow that completes with only stale steps left runs again this many times (run_flow)
LOOP_FLOWS = {"sanity"}  # analysis flows whose fixes go through the fix loop (`q3tui loop`)


@dataclass
class Stage:
    flow: str
    outcome: str  # passed | the flow's outcome when it did not pass
    changed: bool  # it changed the RTL
    cost_usd: float
    note: str = ""


@dataclass
class ChainResult:
    stopped: str  # all passed | <flow> did not pass (…) | <flow> ran N times
    stages: list[Stage] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.stopped == "all passed"


def design_hash(project: Project) -> str:
    """The RTL as it is (src/rtl/, without the smoke test and style-lint output the rtl flow keeps there)."""
    h = hashlib.sha256()
    rtl = project.rtl_dir
    if rtl.is_dir():
        for f in sorted(rtl.rglob("*")):
            rel = f.relative_to(rtl)
            if f.is_file() and not {"smoke", "style_lint"} & set(rel.parts):
                h.update(str(rel).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


async def run_flow(project: Project, bus, name: str) -> tuple[bool, str]:
    """One flow, unattended: (passed, what happened)."""
    from q3tui.pipeline.engine import Engine

    if name in LOOP_FLOWS:
        from q3tui.core import loop

        result = await loop.fix_loop(project, bus, name)
        last = result.rounds[-1] if result.rounds else None
        if result.stopped == "clean":
            return True, f"nothing open after {len(result.rounds) - 1} fix round(s)"
        return False, f"fix loop stopped: {result.stopped}" + (f" ({last.open} open)" if last else "")
    for attempt in range(1 + STALE_RERUNS):
        eng = Engine(project, bus, flow=flows.load_flow(name, project.root))
        outcome = await eng.run(yes=True)
        if outcome != "complete":
            return False, f"ended '{outcome}'"
        views = Engine(project, flow=flows.load_flow(name, project.root)).status()
        left = [v.name for v in views if v.status not in ("done", "user")]
        if not left:
            return True, "complete" + (" (run again: a late step changed what earlier ones were built from)" if attempt else "")
        if any(v.status != "stale" for v in views if v.name in left) or attempt == STALE_RERUNS:
            break
        # only stale steps left: a late step changed what earlier ones were built from (e.g. ppa_optimize's check formatted the RTL after the
        # synthesis that passed) — the flow runs once more on it
        bus.emit("log", message=f"auto: {name}: {', '.join(left)} out of date after the run — running {name} once more")
    return False, f"complete, but not done: {', '.join(left)}"


class ToolFix(BaseModel):
    summary: str = Field(description="the cause, the evidence, and what you changed (or why nothing)")
    rerun: bool = Field(description="true: you changed something that should make it pass, or nothing needed changing (a crash of a busy machine): "
                                    "run the flow again once; false: it needs the user")
    user_action: str = Field("", description="when it needs the user: exactly what they should do")


TOOL_FIXES = 2  # tool fixes per flow run (each followed by a run of the flow)
TOOL_FIX_SYSTEM = """You fix the tool problems of Q3TUI's unattended runs. A step's EDA tool failed (crashed, timed out, missing, called wrongly) — not the design.
You get the error, the end of the tool's log, the tool's role in config/tools.json, the step's options, the machine's memory and the memory the same tool
needed in its earlier runs. Judge the cause from the evidence: a crash (SIGSEGV, rc 139) while the tool's earlier runs needed about as much memory as
the machine has, or more, is the machine running out of memory — then make the run need less (an option the flow's steps offer, e.g. black boxes for
big memories: read the RTL to find them), not a rerun on the same setup. You may change the tool's role (set_tool_role: timeout_s, env, modules), a
setting (get_settings / set_settings) or a step option listed for this (set_step_option), and nothing else: never the tool's command, never the RTL,
the spec or the testbench (you may read them). A crash with nothing to change (a busy machine, a license taken) needs no change: say so and ask for a
rerun. A fix that needs a tool install, a license, a bigger machine or a change to Q3TUI is the user's: change nothing, rerun false, and say exactly
what they should do. Keep it short."""


def tool_failure(project: Project, since: str):
    """The tool failure recorded at or after `since` (an ISO time), the latest (tui/failures.Failure), or None."""
    from q3tui.tui import failures

    found = [f for f in failures.failed(project) if f.kind == "tool" and f.at >= since]
    return found[-1] if found else None


def _tools_for_fix(ops) -> list:
    import json

    from claude_agent_sdk import tool

    def text(s: str) -> dict:
        return {"content": [{"type": "text", "text": s}]}

    @tool("set_tool_role", "Change one field of a tool role in config/tools.json (backed up): timeout_s (seconds), env ({\"VAR\": \"value\"}, merged; null "
                           "removes VAR) or modules (the list of environment modules). value: JSON or plain text. Not the command.",
          {"type": "object", "properties": {"role": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "string"}}, "required": ["role", "key", "value"]})
    async def set_role(a: dict) -> dict:
        if a.get("key") not in ("timeout_s", "env", "modules"):
            return text("only timeout_s, env or modules here: a new command is the user's")
        raw = a.get("value")
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            value = raw
        try:
            return text(ops.set_tool_role(a["role"], a["key"], value))
        except Exception as exc:  # noqa: BLE001 - said to the stage
            return text(f"not changed: {exc}")

    @tool("get_settings", "Every user-facing setting with its current value and help.", {})
    async def get_settings(a: dict) -> dict:
        vals = ops.settings()
        return text("\n".join(f"{s.path} = {json.dumps(vals[s.path])} — {s.help}" for t in ops.settings_tabs() for s in t.settings))

    @tool("set_settings", "Change settings by path (saved to q3tui.yaml), e.g. {\"changes\": {\"<path>\": <value>}}. Not pipeline.auto_*.",
          {"type": "object", "properties": {"changes": {"type": "object"}}, "required": ["changes"]})
    async def set_settings(a: dict) -> dict:
        changes = {k: v for k, v in (a.get("changes") or {}).items() if not str(k).startswith("pipeline.auto_")}
        try:
            return text(ops.apply_settings(changes, True))
        except Exception as exc:  # noqa: BLE001 - said to the stage
            return text(f"not changed: {exc}")

    @tool("set_step_option", "Set an option of a step of this flow (saved to q3tui.yaml, pipeline.step_options) — only the options listed for this "
                             "in your task. value: JSON (a list, a number, text).",
          {"type": "object", "properties": {"step": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "string"}},
           "required": ["step", "key", "value"]})
    async def set_option(a: dict) -> dict:
        raw = a.get("value")
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            value = raw
        try:
            return text(ops.set_step_option(str(a.get("step", "")), str(a.get("key", "")), value))
        except Exception as exc:  # noqa: BLE001 - said to the stage
            return text(f"not changed: {exc}")

    return [set_role, get_settings, set_settings, set_option]


async def fix_tool(project: Project, bus, name: str, failure, tried: list[str] | None = None) -> ToolFix | None:
    """The LLM stage that judges a tool failure and fixes what a role, a setting or an offered step option can fix (`tried`: its earlier fixes of this
    flow run, which did not help). None: it could not run."""
    from q3tui.core.ops import Ops
    from q3tui.llm.runtime import Stage, run_stage
    from q3tui.pipeline.engine import Engine
    from q3tui.tui import failures

    import json

    eng = Engine(project, bus, flow=flows.load_flow(name, project.root))
    ops = Ops(eng)
    parts = [f"# Task: a tool failure in an unattended run\nStep `{failure.step}` of the {name} flow failed at {failure.at}: its tool failed. Judge it, fix "
             "what your tools can fix, and answer.", "", failures.facts(project, failure)]
    if tried:
        parts += ["", "Already tried in this run (the flow failed the same way after it): " + " | ".join(tried)]
    stage = Stage(name="tool_fix", system_prompt=TOOL_FIX_SYSTEM, prompt="\n".join(parts), cwd=project.root, builtin_tools=["Read", "Grep", "Glob"],
                  sdk_tools=_tools_for_fix(ops), output_model=ToolFix, deny_dirs=[project.state_dir], max_turns=25)
    try:
        res = await run_stage(stage, project.cfg, bus.scoped("tool_fix"))
    except Exception as exc:  # noqa: BLE001 - no credentials, a stage that failed: the chain stops as it would have
        bus.emit("warning", message=f"auto: the tool fix could not run: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}")
        return None
    return res.output


async def run_flow_recovering(project: Project, bus, name: str) -> tuple[bool, str]:
    """`run_flow`; when it stopped on a tool failure, the tool fix (`fix_tool`) judges it and the flow runs again — at most TOOL_FIXES times."""
    tried: list[str] = []
    while True:
        since = datetime.now().isoformat(timespec="milliseconds")
        ok, note = await run_flow(project, bus, name)
        if ok:
            return ok, note + (f" (after the tool fix: {tried[-1][:120]})" if tried else "")
        failure = tool_failure(project, since)
        if failure is None:
            return ok, note
        if len(tried) >= TOOL_FIXES:
            return False, f"{note} — the tool of {failure.step} still failed after {len(tried)} tool fix(es) ({tried[-1][:120]})"
        bus.emit("warning", message=f"auto: {name}: the tool of {failure.step} failed ({failure.short()}): not the design — the tool fix judges it")
        fix = await fix_tool(project, bus, name, failure, tried)
        if fix is None:
            return ok, note
        bus.emit("log", message=f"auto: tool fix: {fix.summary}")
        if not fix.rerun:
            return False, f"{note} — the tool fix: {fix.user_action or fix.summary}"
        tried.append(fix.summary)


async def run_chain(project: Project, bus, chain: list[str] | None = None, max_runs: int | None = None) -> ChainResult:
    chain = list(chain or project.cfg.pipeline.chain or DEFAULT_CHAIN)
    for name in chain:
        flows.load_flow(name, project.root)  # (an unknown flow: said before anything runs)
    limit = max_runs or project.cfg.pipeline.chain_max_runs
    project.cfg.pipeline.auto_answer = True  # (unattended: every gate approved, every question answered with its default)
    design = set(project.cfg.pipeline.design_flows)
    last = max((i for i, f in enumerate(chain) if f in design), default=-1)
    checks = set(chain[last + 1:])  # the flows that check the RTL: they pass again with a changed one
    passed_with: dict[str, str] = {}  # flow -> the RTL it passed with
    runs: dict[str, int] = {}
    result = ChainResult("")
    while True:
        now = design_hash(project)
        name = next((f for f in chain if f not in passed_with or (f in checks and passed_with[f] != now)), None)
        if name is None:
            result.stopped = "all passed"
            return result
        if runs.get(name, 0) >= limit:
            result.stopped = f"{name} ran {runs[name]} times and the design still changed after it (pipeline.chain_max_runs)"
            return result
        runs[name] = runs.get(name, 0) + 1
        bus.emit("log", message=f"auto: {name} flow" + (f" again (run {runs[name]}): the RTL changed since it passed" if runs[name] > 1 else ""))
        before, cost0 = now, bus.cost_usd
        ok, note = await run_flow_recovering(project, bus, name)
        after = design_hash(project)
        stage = Stage(name, "passed" if ok else note, after != before, bus.cost_usd - cost0, note)
        result.stages.append(stage)
        if not ok:
            result.stopped = f"{name} did not pass ({note})"
            bus.emit("warning", message=f"auto: stopped — {result.stopped}")
            return result
        passed_with[name] = after
        if after != before:
            stale = [f for f in chain if f in checks and f in passed_with and passed_with[f] != after]
            bus.emit("log", message=f"auto: {name} changed the RTL" + (f": {', '.join(stale)} run again" if stale else ""))


def summary(result: ChainResult) -> str:
    lines = ["flow       result                                          RTL changed  cost"]
    for s in result.stages:
        lines.append(f"{s.flow:<10} {s.outcome[:46]:<47} {'yes' if s.changed else '':<12} ${s.cost_usd:.2f}")
    lines.append(f"stopped: {result.stopped} · total ${sum(s.cost_usd for s in result.stages):.2f}")
    return "\n".join(lines)
