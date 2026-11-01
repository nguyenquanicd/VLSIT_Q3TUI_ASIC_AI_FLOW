"""The engine: runs a flow like `make`, keeps the state of each step, gates, questions and the fix loop
(spec/engine.md). Front ends never call it directly: they call Ops (q3tui.engine.ops)."""

from __future__ import annotations

import asyncio
import copy
import json
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from q3tui.config import ConfigLayers
from q3tui.engine.artifacts import (
    Artifacts,
    backup,
    expand,
    hash_files,
    hash_value,
    json_path,
    read_json,
    restore,
)
from q3tui.engine.checks import Checker
from q3tui.engine.ctx import Changes, Ctx, NoServices, Problem, Services, StepError
from q3tui.engine.decisions import Decisions, Question
from q3tui.engine.events import EventBus
from q3tui.engine.needs import find_package, missing
from q3tui.engine.state import (
    Approval,
    Lock,
    PipelineState,
    Request,
    StepState,
    now,
    step_from_dict,
)
from q3tui.engine.views import review_items
from q3tui.flowdef.load import Lookup
from q3tui.flowdef.model import Flow, Instance
from q3tui.tools.roles import ToolEnv
from q3tui.workspace.approvals import Approvals
from q3tui.workspace.project import Project

DISPLAY_ORDER = ("running", "failed", "missing_input", "question waiting", "stale", "approval waiting", "approved",
                 "done", "pending")
LOOP_OPTIONS = [
    {"id": "fix_again", "text": "Fix again (with your hint)"},
    {"id": "other_input", "text": "The cause is in another input"},
    {"id": "accept", "text": "Accept this problem"},
]


class EngineError(Exception):
    """A user action the engine refuses (with the reason)."""


class StepCode(Protocol):
    async def run(self, ctx: Ctx) -> None: ...

    def check(self, name: str, ctx: Ctx) -> bool | str: ...

    def on_approve(self, ctx: Ctx) -> None: ...


class _NoCode:
    async def run(self, ctx):
        raise StepError("no runner for this step")

    def check(self, name, ctx):
        return f"check_{name}: the step has no code"

    def on_approve(self, ctx):
        return None


@dataclass
class StepStatus:
    id: str
    stage: str
    result: str
    approval: Approval | None
    display: str
    origin: str
    edited: list[str]
    open_questions: int
    blocking_questions: int
    pending_reviews: int
    reason: str = ""
    missing: list[str] = field(default_factory=list)
    definition_changed: bool = False
    cost_usd: float = 0.0


@dataclass
class StageOutcome:
    stage: str
    outcome: str  # complete | waiting | failed | blocked | cancelled
    reason: str = ""


@dataclass
class Scope:
    only: str | None = None
    from_: str | None = None
    to: str | None = None
    stage: str | None = None

    def as_dict(self) -> dict:
        return {k.rstrip("_"): v for k, v in asdict(self).items() if v}


class Engine:
    def __init__(self, project: Project, flow: Flow, config: ConfigLayers, lookup: Lookup, *,
                 code_for: Callable[[Instance], StepCode] | None = None, services: Services | None = None,
                 bus: EventBus | None = None, allow_run: Callable[[Instance, str], bool] | None = None,
                 approvals: Approvals | None = None, tool_env: ToolEnv | None = None):
        if not flow.ok:
            raise EngineError("the flow has errors:\n" + "\n".join(map(str, flow.problems)))
        self.project, self.flow, self.config, self.lookup = project, flow, config, lookup
        self.root = project.root
        self.code_for = code_for or (lambda inst: _NoCode())
        self.services: Services = services or NoServices()
        self.allow_run = allow_run
        self.bus = bus or EventBus(project.events_file)
        self.state = PipelineState.load(project.pipeline_file)
        self.decisions = Decisions(project.decisions_file)
        self.artifacts = Artifacts(flow, project.root)
        self.lock = Lock(project.lock_file)
        self.approvals = approvals
        self.tool_env = tool_env or ToolEnv(config.config, approved=self._setup_approved)
        self.run_id = ""
        self.running: dict[str, asyncio.Task] = {}
        self._run_task: asyncio.Task | None = None
        self._stopping = False
        self._run_cost = 0.0
        self._cancelled: set[str] = set()
        self._recover()

    # -- persistence ----------------------------------------------------------------------------

    def save(self) -> None:
        self.state.save(self.project.pipeline_file)
        self.decisions.save()

    def emit(self, kind: str, step: str = "", **fields) -> None:
        stage = self.flow.stage_of(step).name if step in self.flow.instances else ""
        self.bus.emit(kind, run_id=self.run_id, stage=stage, step=step, **fields)

    def _setup_approved(self, command: str) -> bool:
        """A `setup_script` from the project layer runs only once you allowed it."""
        if self.config.source("tools.setup_script") != "project":
            return True
        return self.approvals is not None and self.approvals.allowed(self.root, "command", command)

    def tool_available(self, role: str) -> str | None:
        self.tool_env.ensure(self.config.config)
        return self.tool_env.available(role)

    @property
    def is_running(self) -> bool:
        return bool(self.running) or (self._run_task is not None and not self._run_task.done())

    def _recover(self) -> None:
        """A step left `running` by a process that died: put its outputs and its state back."""
        recovered = False
        for sid, st in list(self.state.steps.items()):
            if st.result != "running" or sid not in self.flow.instances:
                continue
            started = st.started or {}
            if started.get("backup"):
                restore(Path(started["backup"]), self.root, self._output_files(self.flow.instances[sid]))
            self.state.steps[sid] = step_from_dict(started["before"]) if started.get("before") else StepState()
            self.bus.emit("warning", step=sid, message=f"{sid} was interrupted; its outputs were put back")
            recovered = True
        if recovered:
            self.state.save(self.project.pipeline_file)

    # -- what each step reads and writes ---------------------------------------------------------

    def _output_files(self, inst: Instance, *, generated_only: bool = False) -> list[Path]:
        files: list[Path] = []
        for o in inst.outputs:
            if generated_only and o.mode == "seed":
                continue
            files += self.artifacts.files(o.artifact)
        return sorted(set(files))

    def _current_inputs(self, inst: Instance) -> dict[str, str]:
        """Everything in the step's hash, each with its own hash (spec/engine.md "Staleness and updates")."""
        out: dict[str, str] = {}
        for i in inst.inputs:
            if i.hashed:
                out[f"input:{i.artifact}"] = self.artifacts.hash(i.artifact, inst)
        for o in inst.outputs:
            if o.mode == "seed":
                h = self.artifacts.hash(o.artifact)
                if h:
                    out[f"seed:{o.artifact}"] = h
        for a in inst.assets:
            f = self.lookup.file(a)
            out[f"asset:{a}"] = hash_files([f], f.parent) if f else ""
        for name, p in inst.param_decls.items():
            if p.affects_result:
                out[f"param:{name}"] = hash_value(inst.params.get(name))
        pending = self.state.step(inst.id).pending_requests()
        if pending:
            out["requests"] = hash_value([r.id for r in pending])
        return out

    def gate(self, sid: str) -> str:
        """The gate in effect: the config's (the highest layer that sets it), else the flow files'."""
        return self.config.gate_mode(sid) or self.flow.instances[sid].flow_gate

    def is_stale(self, sid: str) -> bool:
        st = self.state.steps.get(sid)
        if st is None or st.result != "done" or st.origin == "user":
            return False
        return hash_value(self._current_inputs(self.flow.instances[sid])) != st.hash

    def edited(self, sid: str) -> list[str]:
        """The outputs of the step changed by hand since it wrote them."""
        out = []
        for o in self.flow.instances[sid].outputs:
            last = self.state.artifacts.get(o.artifact)
            if o.mode != "seed" and last and last.get("by") == sid and self.artifacts.hash(o.artifact) != last["hash"]:
                out.append(o.artifact)
        return out

    def missing(self, sid: str) -> list[str]:
        return missing(self.flow.instances[sid], self.artifacts, self.lookup, self.tool_available, self.root)

    def units(self, sid: str) -> list[str]:
        inst = self.flow.instances[sid]
        if not inst.units:
            return []
        art, _, path = str(inst.units["from"]).partition(" ")
        try:
            values = json_path(read_json(self.artifacts.files(art, inst)), path.strip() or "$")
        except (OSError, ValueError, FileNotFoundError):
            return []
        if len(values) == 1 and isinstance(values[0], list):
            values = values[0]
        return [str(v) for v in values]

    # -- status ---------------------------------------------------------------------------------

    def result(self, sid: str) -> tuple[str, list[str]]:
        st = self.state.steps.get(sid) or StepState()
        if st.result in ("running", "failed"):
            return st.result, []
        if st.result == "done":
            return ("stale" if self.is_stale(sid) else "done"), []
        if self._user_file(sid):  # taken as yours when the run reaches it, whatever the step lacks
            return "pending", []
        lacks = self.missing(sid)
        return ("missing_input", lacks) if lacks else ("pending", [])

    def status(self, sid: str) -> StepStatus:
        st = self.state.steps.get(sid) or StepState()
        result, lacks = self.result(sid)
        open_q = self.decisions.open_of(sid)
        blocking = [q for q in open_q if q.blocking]
        reviews = sum(1 for items in st.reviews.values() for v in items.values() if v.get("status") != "confirmed")
        approval = st.approval if result in ("done", "stale") else None
        if result == "running":
            display = "running"
        elif result == "failed":
            display = "failed"
        elif result == "missing_input":
            display = "missing_input"
        elif blocking:
            display = "question waiting"
        elif result == "stale":
            display = "stale"
        elif approval and approval.status == "waiting":
            display = "approval waiting"
        elif result == "done" and approval and approval.by == "you":
            display = "approved"
        elif result == "done":
            display = "done"
        else:
            display = "pending"
        inst = self.flow.instances[sid]
        definition = st.definition or {}
        changed = bool(st.ran and definition.get("hash") and definition["hash"] != inst.definition_hash
                       and definition.get("later") != inst.definition_hash)
        return StepStatus(sid, inst.stage, result, approval, display, st.origin,
                          self.edited(sid) if result in ("done", "stale") else [], len(open_q), len(blocking),
                          reviews, st.reason or "; ".join(lacks), lacks, changed, st.cost_usd)

    def settled_for_feed(self, sid: str) -> bool:
        """`done`, and waiting neither for approval nor for an answer: the steps after it may start."""
        st = self.state.steps.get(sid)
        if st is None or st.result != "done" or self.is_stale(sid):
            return False
        if not st.approval or st.approval.status != "approved":
            return False
        return not self.decisions.open_of(sid, blocking=True) and not st.loop.pending

    # -- scope ----------------------------------------------------------------------------------

    def scope_steps(self, scope: Scope | None) -> list[str]:
        order = self.flow.order()
        if scope is None or not scope.as_dict():
            return order
        for name in (scope.only, scope.from_, scope.to):
            if name is not None and name not in self.flow.instances:
                raise EngineError(f"no step `{name}` in the flow")
        if scope.stage is not None:
            if scope.stage not in {s.name for s in self.flow.stages}:
                raise EngineError(f"no stage `{scope.stage}` in the flow")
            return [s for s in order if self.flow.stage_of(s).name == scope.stage]
        if scope.only is not None:
            return [scope.only]
        chosen = set(order)
        if scope.from_ is not None:
            st = self.flow.stage_of(scope.from_)
            first = set(st.steps[st.steps.index(scope.from_):])
            down: set[str] = set(first)
            for s in first:
                down |= {d for d in self.flow.downstream(s)}
            stages = {self.flow.stage_of(s).name for s in down - set(st.steps)}
            chosen &= first | {s for s in order if self.flow.stage_of(s).name in stages}
        if scope.to is not None:
            st = self.flow.stage_of(scope.to)
            head = set(st.steps[:st.steps.index(scope.to) + 1])
            up: set[str] = set()
            for s in head:
                up |= self.flow.upstream(s)
            stages = {self.flow.stage_of(s).name for s in up - set(st.steps)}
            chosen &= head | {s for s in order if self.flow.stage_of(s).name in stages}
        return [s for s in order if s in chosen]

    # -- running ----------------------------------------------------------------------------------

    def start(self, scope: Scope | None = None, *, rerun: list[str] = (), regenerate: list[str] = ()) -> asyncio.Task:
        """Start a run in the background (the TUI); `await engine.run(...)` waits for it."""
        if self.is_running:
            raise EngineError("a run is going on")
        self._run_task = asyncio.ensure_future(self.run(scope, rerun=rerun, regenerate=regenerate))
        return self._run_task

    async def run(self, scope: Scope | None = None, *, rerun: list[str] = (),
                  regenerate: list[str] = ()) -> list[StageOutcome]:
        if self.running:
            raise EngineError("a run is going on")
        steps = self.scope_steps(scope)
        for sid in [*rerun, *regenerate]:
            if sid not in self.flow.instances:
                raise EngineError(f"no step `{sid}` in the flow")
        steps = [s for s in self.flow.order() if s in set(steps) | set(rerun) | set(regenerate)]
        in_scope = set(steps)
        not_ready = sorted({d for s in steps for d in self.flow.upstream(s) - in_scope if not self.settled_for_feed(d)})
        if not_ready:
            raise EngineError(f"these steps outside the scope are not ready: {', '.join(not_ready)}")
        self.lock.acquire()
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._stopping, self._run_cost, self._cancelled = False, 0.0, set()
        forced = {s: "rerun" for s in rerun} | {s: "regenerate" for s in regenerate}
        failed_now: set[str] = set()
        started_stages: set[str] = set()
        stages = [st.name for st in self.flow.stages if any(s in in_scope for s in st.steps)]
        self.emit("run_started", scope=(scope.as_dict() if scope else {}), steps=steps)
        try:
            await self._schedule(steps, forced, failed_now, started_stages)
        finally:
            outcomes = self._outcomes(stages, in_scope)
            for o in outcomes:
                self.bus.emit("stage_finished", run_id=self.run_id, stage=o.stage, outcome=o.outcome, reason=o.reason)
            self.emit("run_finished", outcomes={o.stage: o.outcome for o in outcomes}, cost_usd=round(self._run_cost, 4))
            self.save()
            self.lock.release()
            self.run_id = ""
        return outcomes

    def _cost_reached(self) -> bool:
        limit = self.config.config.pipeline.max_cost
        return limit is not None and self._run_cost >= limit

    def _wants(self, sid: str, forced: dict, failed_now: set) -> bool:
        if sid in forced:
            return True
        result, _ = self.result(sid)
        if result in ("pending", "stale"):
            return True
        return result == "failed" and sid not in failed_now

    def _can_start(self, sid: str) -> bool:
        for d in self.flow.upstream(sid):
            if d in self.running or not self.settled_for_feed(d):
                return False
        return True

    async def _schedule(self, steps: list[str], forced: dict, failed_now: set, started_stages: set) -> None:
        limit = self.config.config.pipeline.max_parallel_stage
        while True:
            progressed = False
            if not self._stopping and not self._cost_reached():
                for sid in steps:
                    if sid in self.running or not self._wants(sid, forced, failed_now) or not self._can_start(sid):
                        continue
                    stage = self.flow.stage_of(sid).name
                    active = {self.flow.stage_of(r).name for r in self.running}
                    if stage not in active and len(active) >= limit:
                        continue
                    mode = forced.pop(sid, None)
                    if mode is None and self._take_user_file(sid):
                        progressed = True
                        continue
                    lacks = self.missing(sid)
                    if lacks:
                        continue
                    if stage not in started_stages:
                        started_stages.add(stage)
                        self.bus.emit("stage_started", run_id=self.run_id, stage=stage)
                    self.running[sid] = asyncio.ensure_future(self._run_step(sid, mode))
                    progressed = True
            if not self.running:
                if progressed and not self._stopping:
                    continue
                return
            done, _ = await asyncio.wait(list(self.running.values()), return_when=asyncio.FIRST_COMPLETED)
            for sid, task in list(self.running.items()):
                if task in done:
                    del self.running[sid]
                    if task.cancelled() or task.result() == "cancelled":
                        self._cancelled.add(sid)
                    elif task.result() == "failed":
                        failed_now.add(sid)

    def stop(self) -> None:
        """Stop the whole run: the running steps are cancelled and put back as they were."""
        self._stopping = True
        for task in self.running.values():
            task.cancel()

    def _user_file(self, sid: str) -> bool:
        st = self.state.steps.get(sid)
        if st is not None and (st.ran or st.origin == "user"):
            return False
        return any(o.user_provided and self.artifacts.exists(o.artifact) for o in self.flow.instances[sid].outputs)

    def _take_user_file(self, sid: str) -> bool:
        """A `user_provided` output you placed before the step ever ran: the step is done, origin user."""
        if not self._user_file(sid):
            return False
        st = self.state.step(sid)
        inst = self.flow.instances[sid]
        st.result, st.origin, st.reason = "done", "user", ""
        st.approval = Approval("approved", "you", now())
        st.outputs = {o.artifact: self.artifacts.hash(o.artifact) for o in inst.outputs}
        st.inputs = self._current_inputs(inst)
        st.hash = hash_value(st.inputs)
        self.emit("step_skipped", step=sid, reason="user")
        self.save()
        return True

    def _safe_code(self, inst: Instance) -> StepCode:
        try:
            return self.code_for(inst)
        except Exception as exc:  # noqa: BLE001 -- reported; the step then has no code to call
            self.emit("error", step=inst.id, message=f"the code of {inst.id} does not load: {exc}")
            return _NoCode()

    def _allow_run(self, inst: Instance) -> Callable[[str], bool] | None:
        if self.allow_run is None:
            return None
        return lambda command: self.allow_run(inst, command)

    # -- one step ---------------------------------------------------------------------------------

    def changes(self, sid: str, mode: str | None = None) -> Changes:
        inst = self.flow.instances[sid]
        st = self.state.step(sid)
        ch = Changes(first_run=not st.ran or mode == "regenerate")
        if not ch.first_run:
            current = self._current_inputs(inst)
            for key in sorted(set(current) | set(st.inputs)):
                if not key.startswith(("input:", "seed:", "asset:")):
                    continue
                old, new = st.inputs.get(key, ""), current.get(key, "")
                if old != new:
                    change = "added" if not old else "removed" if not new else "changed"
                    ch.inputs.append({"artifact": key.split(":", 1)[1], "change": change})
            for name, p in inst.param_decls.items():
                if p.affects_result and name in st.params and st.params[name] != inst.params.get(name):
                    ch.params.append({"name": name, "old": st.params[name], "new": inst.params.get(name)})
            old_files = (st.definition or {}).get("files") or {}
            if old_files and (st.definition or {}).get("hash") != inst.definition_hash:
                ch.definition_changed = sorted(k for k in set(old_files) | set(inst.definition_files)
                                               if old_files.get(k) != inst.definition_files.get(k))
            ch.edited_outputs = self.edited(sid)
        ch.requests = [{"source": r.source, "text": r.text, "unit": r.unit, "kind": r.kind, "key": r.key}
                       for r in st.pending_requests()]
        return ch

    def _visible_steps(self, sid: str) -> set[str]:
        """The steps whose outputs the step's LLM may read, directly or through other steps."""
        seen: set[str] = {sid}
        todo = [sid]
        while todo:
            inst = self.flow.instances[todo.pop()]
            for i in inst.inputs:
                if not i.llm_visible:
                    continue
                writers = [w for w in [self.flow.producers.get(i.artifact), *self.flow.updaters.get(i.artifact, [])] if w]
                for w in writers:
                    if w not in seen:
                        seen.add(w)
                        todo.append(w)
        return seen

    def _ctx(self, inst: Instance, changes: Changes) -> Ctx:
        sid = inst.id
        visible = self._visible_steps(sid)
        settled = [{"key": q.key, "kind": q.kind, "text": q.text, "answer": q.answer, "step": q.step, "by": q.by}
                   for q in self.decisions.questions if q.settled and q.step in visible and q.problem is None]
        settled_keys = {q.key: q.answer for q in self.decisions.questions if q.settled and q.problem is None}
        params = dict(inst.params)
        for name, p in inst.param_decls.items():
            if p.type == "path" and params.get(name):
                params[name] = str(expand(str(params[name]), self.root))
        ctx = Ctx(
            inst, params=params,
            inputs={i.artifact: self.artifacts.files(i.artifact, inst) for i in inst.inputs},
            assets={a: f for a in inst.assets if (f := self.lookup.file(a)) is not None},
            packages={pk["name"]: f for pk in inst.packages if (f := find_package(pk["name"], self.lookup))},
            outputs={o.artifact: self.artifacts.target(o.artifact) for o in inst.outputs},
            units=self.units(sid), changes=changes, settled=settled, services=self.services,
            settled_keys=settled_keys, emit=lambda kind, msg: self.emit(kind, step=sid, message=msg),
            root=self.root, work=self.project.work_dir(sid))
        ctx._add_cost = lambda usd: self.add_cost(sid, usd)
        ctx._emit_event = lambda kind, **fields: self.emit(kind, step=sid, **fields)
        ctx._regenerate = changes.first_run
        ctx._project = self.project
        ctx._config = self.config.config
        ctx._lookup = self.lookup
        ctx._instance = inst
        ctx._stage = self.flow.stage_of(sid)
        ctx._allowed = self._readable(inst)
        ctx._tool_available = self.tool_available
        ctx._code = None
        return ctx

    def _hook(self, name: str, *args) -> None:
        """Tell the services (LLM runtime) where the step is in its life: started, finished."""
        fn = getattr(self.services, name, None)
        if fn is not None:
            try:
                fn(*args)
            except Exception as exc:  # noqa: BLE001 -- a service's bookkeeping never breaks the run
                self.emit("warning", step=args[0]._instance.id, message=f"{name}: {exc}")

    def _readable(self, inst: Instance) -> dict[str, list[Path]]:
        """What the step's LLM may read and write (spec/flow.md "What the LLM may read")."""
        read: list[Path] = []
        for i in inst.inputs:
            if i.llm_visible:
                read += self.artifacts.files(i.artifact, inst)
                if i.artifact in self.flow.producers:
                    read.append(self.artifacts.target(i.artifact))
        read += [f for a in inst.assets if (f := self.lookup.file(a)) is not None]
        own = [t for o in inst.outputs if (t := self.artifacts.target(o.artifact)) is not None]
        read += [p for s in inst.skills if (p := self.lookup.folder("skills", s)) is not None]
        read += [expand(str(inst.params[n]), self.root) for n, p in inst.param_decls.items()
                 if p.type == "path" and inst.params.get(n)]
        read += [f for pk in inst.packages if (f := find_package(pk["name"], self.lookup))]
        write = [t for w in inst.write if (t := self.artifacts.target(w)) is not None]
        return {"read": read + own, "write": write}

    def add_cost(self, sid: str, usd: float) -> None:
        if not usd:
            return
        self.state.step(sid).cost_usd += usd
        self.state.cost_usd += usd
        self._run_cost += usd

    async def _run_step(self, sid: str, mode: str | None) -> str:
        box: dict = {}
        result = "failed"
        try:
            result = await self._run_step_body(sid, mode, box)
            return result
        except asyncio.CancelledError:
            result = "cancelled"
            raise
        finally:
            if "ctx" in box:
                self._hook("step_finished", box["ctx"], result)

    async def _run_step_body(self, sid: str, mode: str | None, box: dict) -> str:
        inst = self.flow.instances[sid]
        st = self.state.step(sid)
        before = copy.deepcopy(st)
        changes = self.changes(sid, mode)
        files_before = self._output_files(inst)
        bdir = self.project.backups / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{sid}-start"
        backup(files_before, self.root, bdir)
        if mode == "regenerate":
            for f in self._output_files(inst, generated_only=True):
                f.unlink(missing_ok=True)
        snapshot = self._current_inputs(inst)
        delivered = [r.id for r in st.pending_requests()]
        seeds_before = {o.artifact: {f: f.read_bytes() for f in self.artifacts.files(o.artifact)}
                        for o in inst.outputs if o.mode == "seed"}
        outputs_before = {o.artifact: self.artifacts.hash(o.artifact) for o in inst.outputs}
        st.started = {"backup": str(bdir), "before": asdict(before)}
        st.result, st.reason = "running", ""
        self.save()
        self.emit("step_started", step=sid, changes=changes.summary(), regenerate=mode == "regenerate")
        ctx = self._ctx(inst, changes)
        box["ctx"] = ctx
        cost_before = st.cost_usd
        code = _NoCode()
        try:
            code = self.code_for(inst)
            ctx._code = code
            self._hook("step_started", ctx)
            await code.run(ctx)
            for art, kept in seeds_before.items():  # a seed, once written, is yours: never overwritten
                now_files = {f: f.read_bytes() for f in self.artifacts.files(art)}
                if kept and now_files != kept:
                    for f in now_files:
                        if f not in kept:
                            f.unlink()
                    for f, data in kept.items():
                        f.write_bytes(data)
                    self.emit("warning", step=sid, message=f"{sid} rewrote its seed `{art}`; it was put back")
            self._check_schemas(inst)
        except asyncio.CancelledError:
            restore(bdir, self.root, self._output_files(inst))
            self.state.steps[sid] = before
            self.save()
            self.emit("step_finished", step=sid, result="cancelled", cost_usd=0.0, outputs=[], error="stopped")
            return "cancelled"
        except Exception as exc:  # noqa: BLE001 -- the step failed: its message is the reason
            st.result, st.reason, st.started = "failed", str(exc) or type(exc).__name__, None
            self.save()
            self.emit("step_finished", step=sid, result="failed", cost_usd=round(st.cost_usd - cost_before, 4),
                      outputs=[], error=st.reason)
            return "failed"
        accepted = [list(a) for a in st.loop.accepted]
        problems = [p for p in ctx._problems if p.ident not in accepted]
        failed_checks = []
        if not problems:
            results = Checker(inst, self.artifacts, self.root, tools=ctx._tools,
                              code_check=lambda name: code.check(name, ctx), allow_run=self._allow_run(inst)).run_all()
            for r in results:
                if r.status == "fail" and r.on_fail == "fail":
                    failed_checks.append(f"{r.check}: {r.reason}")
                elif r.status == "fail":
                    self.emit("warning", step=sid, message=f"check `{r.check}`: {r.reason}")
                elif r.status == "na":
                    self.emit("log", step=sid, message=f"check `{r.check}`: N/A ({r.reason})")
        if failed_checks:
            st.result, st.reason, st.started = "failed", "; ".join(failed_checks), None
            st.tools = ctx._tools
            self.save()
            self.emit("step_finished", step=sid, result="failed", cost_usd=round(st.cost_usd - cost_before, 4),
                      outputs=[], error=st.reason)
            return "failed"
        self._record(inst, st, snapshot, delivered, ctx)
        outputs_after = dict(st.outputs)
        self._settle_questions(inst, ctx)
        self._update_reviews(inst, st)
        self._approve_after_run(inst, st, before, changes, outputs_before == outputs_after, ctx, code)
        self.emit("step_finished", step=sid, result="done", cost_usd=round(st.cost_usd - cost_before, 4),
                  outputs=sorted({self.project.rel(f) for f in self._output_files(inst)}), error=None)
        open_q = self.decisions.open_of(sid)
        if open_q:
            self.emit("questions", step=sid, open=len(open_q), ids=[q.id for q in open_q])
        if st.approval and st.approval.status == "waiting":
            self.emit("approval_waiting", step=sid, open_questions=len(open_q),
                      files=sorted({self.project.rel(f) for f in self._output_files(inst)}))
        if ctx._problems:
            self._loop_round(sid, problems)
        elif st.loop.round or st.loop.last or st.loop.best:
            self._loop_pass(sid)
        self.save()
        return "done"

    def _check_schemas(self, inst: Instance) -> None:
        import jsonschema

        for o in inst.outputs:
            if not o.schema:
                continue
            schema = json.loads((inst.folder / o.schema).read_text())
            for f in self.artifacts.files(o.artifact):
                try:
                    jsonschema.validate(json.loads(f.read_text()), schema)
                except (ValueError, jsonschema.ValidationError) as exc:
                    msg = exc.message if isinstance(exc, jsonschema.ValidationError) else str(exc)
                    raise StepError(f"`{self.project.rel(f)}` does not match {o.schema}: {msg}") from exc

    def _record(self, inst: Instance, st: StepState, snapshot: dict, delivered: list[int], ctx: Ctx) -> None:
        for r in st.requests:
            if r.id in delivered:
                r.status = "delivered"
        # What the step read, as it was when it started; except its own outputs (an update reads what it writes)
        # and its seeds, taken as they are now. Requests are never recorded: one still pending makes it stale.
        current = self._current_inputs(inst)
        own = {f"input:{o.artifact}" for o in inst.outputs}
        recorded = {k: (current.get(k, "") if k in own else v) for k, v in snapshot.items()
                    if k != "requests" and not k.startswith("seed:")}
        recorded |= {k: v for k, v in current.items() if k.startswith("seed:")}
        st.inputs, st.hash = recorded, hash_value(recorded)
        st.params = {n: inst.params.get(n) for n, p in inst.param_decls.items() if p.affects_result}
        st.outputs = {o.artifact: self.artifacts.hash(o.artifact) for o in inst.outputs}
        for o in inst.outputs:
            self.state.artifacts[o.artifact] = {"hash": st.outputs[o.artifact], "by": inst.id}
        st.definition = {"hash": inst.definition_hash, "version": inst.version, "files": inst.definition_files}
        st.tools = ctx._tools
        st.result, st.reason, st.origin, st.ran, st.started = "done", "", "generated", True, None
        st.finished_at = now()

    def _settle_questions(self, inst: Instance, ctx: Ctx) -> None:
        asked = set()
        for a in ctx._asked:
            q = self.decisions.ask(inst.id, a.kind, a.key, a.text, a.default, a.options, a.blocking)
            asked.add(q.id)
        for q in self.decisions.of_step(inst.id, "open"):
            if q.id not in asked and q.problem is None:
                self.decisions.drop(q)

    def _update_reviews(self, inst: Instance, st: StepState) -> None:
        confirm_all = self.config.config.pipeline.auto_confirm_reviews
        reviews: dict[str, dict] = {}
        for o in inst.outputs:
            items = review_items(o.view, self.artifacts.files(o.artifact))
            if not items:
                continue
            old = st.reviews.get(o.artifact, {})
            reviews[o.artifact] = {
                item: {"hash": h, "status": "confirmed" if confirm_all else
                       (old[item]["status"] if item in old and old[item].get("hash") == h else "not_reviewed")}
                for item, h in items.items()
            }
        st.reviews = reviews

    def _approve_after_run(self, inst: Instance, st: StepState, before: StepState, changes: Changes,
                           unchanged: bool, ctx: Ctx, code: StepCode) -> None:
        gate = self.gate(inst.id)
        was_approved = before.approval is not None and before.approval.status == "approved" and before.ran
        only_decisions = (not changes.first_run and not changes.inputs and not changes.params
                          and not changes.definition_changed and changes.requests
                          and all(r["source"] == "decision" for r in changes.requests))
        open_q = self.decisions.open_of(inst.id)
        if gate == "unattended":
            for q in open_q:
                self.decisions.settle(q, "defaulted", q.default, "auto")
                self.emit("question_answered", step=inst.id, id=q.id, status="defaulted", by="auto")
        elif gate == "auto":
            for q in open_q:
                if not q.blocking:
                    self.decisions.settle(q, "defaulted", q.default, "auto")
                    self.emit("question_answered", step=inst.id, id=q.id, status="defaulted", by="auto")
        if was_approved and (unchanged or only_decisions):
            st.approval = before.approval
            return
        if gate == "manual":
            st.approval = Approval("waiting")
            return
        st.approval = Approval("approved", "auto", now())
        self._on_approve(inst, code)

    def _on_approve(self, inst: Instance, code: StepCode | None = None) -> None:
        code = code or self._safe_code(inst)
        try:
            ctx = self._ctx(inst, Changes(first_run=False))
            ctx._code = code
            code.on_approve(ctx)
        except Exception as exc:  # noqa: BLE001 -- on_approve must not break an approval
            self.emit("error", step=inst.id, message=f"on_approve of {inst.id}: {exc}")

    # -- fix loop -------------------------------------------------------------------------------

    def receivers_of(self, checker: str) -> set[str]:
        return {r for k in self.flow.instances[checker].handback if (r := self.flow.receivers.get(k))}

    def segment(self, checker: str, receivers: set[str] | None = None) -> set[str]:
        """The steps of a loop: from each step that receives its problems to the checking step."""
        out = {checker}
        up = self.flow.upstream(checker)
        for r in receivers if receivers is not None else self.receivers_of(checker):
            out.add(r)
            out |= self.flow.downstream(r) & up
        return out

    def _loop_round(self, checker: str, problems: list[Problem]) -> None:
        st = self.state.step(checker)
        lp = st.loop
        if not problems:  # every problem was accepted
            self._loop_pass(checker)
            return
        for p in problems:
            receiver = self.flow.receivers.get(p.kind)
            units = self.units(receiver) if receiver else []
            if units and p.unit not in units:
                self.emit("warning", step=checker, message=f"problem {p.kind}: `{p.unit}` is not a unit of {receiver}")
        idents = sorted(p.ident for p in problems)
        if lp.best is None or len(problems) <= lp.best["count"]:
            self._save_best(checker, problems)
        reason = None
        if lp.round > 0 and lp.last is not None and sorted(lp.last) == idents:
            reason = "same_problems"
        elif lp.round >= self.config.config.pipeline.max_fix_rounds:
            reason = "max_rounds"
        lp.last = idents
        if reason:
            self._loop_stop(checker, reason)
            return
        lp.pending = [asdict(p) for p in problems]
        gate = self.gate(checker)
        if gate == "unattended" or (gate == "auto" and not self.decisions.open_of(checker, blocking=True)):
            self._send_problems(checker)

    def _send_problems(self, checker: str) -> None:
        st = self.state.step(checker)
        lp = st.loop
        if not lp.pending:
            return
        sent_to = set()
        for p in lp.pending:
            receiver = self.flow.receivers[p["kind"]]
            self._add_request(receiver, "fix", p["text"], unit=p["unit"], kind=p["kind"], key=p["key"])
            sent_to.add(receiver)
        lp.round += 1
        self.emit("loop_round", step=checker, round=lp.round, problems=len(lp.pending), sent_to=sorted(sent_to))
        lp.pending = []
        self.save()

    def _loop_pass(self, checker: str) -> None:
        lp = self.state.step(checker).loop
        best = (lp.best or {}).get("round")
        lp.round, lp.last, lp.best, lp.pending, lp.stopped = 0, None, None, [], False
        shutil.rmtree(self.project.loop_dir(checker) / "best", ignore_errors=True)
        self.emit("loop_stopped", step=checker, reason="pass", best_round=best)

    def _save_best(self, checker: str, problems: list[Problem]) -> None:
        lp = self.state.step(checker).loop
        seg = self.segment(checker)
        d = self.project.loop_dir(checker) / "best"
        shutil.rmtree(d, ignore_errors=True)
        files = sorted({f for s in seg for f in self._output_files(self.flow.instances[s], generated_only=True)})
        backup(files, self.root, d)
        arts = {o.artifact for s in seg for o in self.flow.instances[s].outputs}
        meta = {"round": lp.round, "count": len(problems), "problems": [asdict(p) for p in problems],
                "steps": {s: asdict(self.state.step(s)) for s in seg},
                "artifacts": {a: self.state.artifacts[a] for a in arts if a in self.state.artifacts}}
        (d / "state.json").write_text(json.dumps(meta, default=str))
        lp.best = {"round": lp.round, "count": len(problems)}

    def _loop_stop(self, checker: str, reason: str) -> None:
        st = self.state.step(checker)
        lp = copy.deepcopy(st.loop)
        d = self.project.loop_dir(checker) / "best"
        problems: list[dict] = list(lp.pending) or []
        if (d / "state.json").is_file():
            meta = json.loads((d / "state.json").read_text())
            seg = set(meta["steps"])
            current = sorted({f for s in seg for f in self._output_files(self.flow.instances[s], generated_only=True)})
            bdir = self.project.backups / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-loop-{checker}"
            backup(current, self.root, bdir)
            restore(d, self.root, current)
            for s, data in meta["steps"].items():
                self.state.steps[s] = step_from_dict(data)
            self.state.artifacts.update(meta["artifacts"])
            problems = meta["problems"]
        st = self.state.step(checker)
        st.loop = lp
        st.loop.pending, st.loop.stopped = [], True
        self.emit("loop_stopped", step=checker, reason=reason, best_round=(lp.best or {}).get("round"))
        gate = self.gate(checker)
        for p in problems:
            receiver = self.flow.receivers.get(p["kind"])
            q = self.decisions.ask(
                checker, p["kind"], f"loop:{checker}:{p['kind']}:{p['unit']}:{p['key']}",
                f"{p['kind']} on {p['unit']} ({p['key']}) is still there after the fix loop: {p['text']}",
                "accept", LOOP_OPTIONS, True,
                problem={"kind": p["kind"], "unit": p["unit"], "key": p["key"], "checker": checker,
                         "receiver": receiver, "text": p["text"]})
            if gate == "unattended":
                self.answer(q.id, "accept", by="auto")
        open_q = self.decisions.open_of(checker)
        if open_q:
            self.emit("questions", step=checker, open=len(open_q), ids=[q.id for q in open_q])
        self.save()

    def _loops_touching(self, sid: str) -> list[str]:
        return [c for c, st in self.state.steps.items()
                if c in self.flow.instances and (st.loop.round or st.loop.stopped) and sid in self.segment(c)]

    def _reset_round(self, sid: str) -> None:
        for c in self._loops_touching(sid):
            lp = self.state.step(c).loop
            lp.round, lp.stopped, lp.last = 0, False, None

    # -- user actions (through Ops) -------------------------------------------------------------

    def _add_request(self, sid: str, source: str, text: str, **extra) -> Request:
        st = self.state.step(sid)
        r = Request(self.state.next_request, source, text, **extra)
        self.state.next_request += 1
        st.requests.append(r)
        return r

    def request_change(self, sid: str, text: str, unit: str | None = None, *, by: str = "you") -> Request:
        if sid not in self.flow.instances:
            raise EngineError(f"no step `{sid}`")
        if unit is not None:
            units = self.units(sid)
            if units and unit not in units:
                raise EngineError(f"`{unit}` is not a unit of {sid} ({', '.join(units)})")
        st = self.state.step(sid)
        r = self._add_request(sid, "you", text, unit=unit)
        if st.approval and st.approval.status == "waiting":
            st.approval = None
            st.loop.pending = []  # a change request instead of an approval sends nothing
            self.emit("approval_resolved", step=sid, decision="change_requested", by=by, accepted_defaults=[],
                      text=text)
        self._reset_round(sid)
        self.save()
        return r

    def approve(self, sid: str, *, force: bool = False, by: str = "you") -> None:
        st = self.state.steps.get(sid)
        if st is None or st.result != "done":
            raise EngineError(f"{sid} has no result to approve")
        if st.approval and st.approval.status == "approved":
            raise EngineError(f"{sid} is already approved")
        if not force:
            blocking = self.decisions.open_of(sid, blocking=True)
            if blocking:
                raise EngineError(f"{sid} has {len(blocking)} blocking question(s): answer them first")
            reviews = sum(1 for items in st.reviews.values() for v in items.values() if v.get("status") != "confirmed")
            if reviews:
                raise EngineError(f"{sid} has {reviews} item(s) not reviewed")
        accepted = []
        for q in self.decisions.open_of(sid):
            if not q.blocking or force:
                if q.problem is not None:
                    continue
                self.decisions.settle(q, "defaulted", q.default, by)
                accepted.append(q.id)
        st.approval = Approval("approved", by, now())
        self._on_approve(self.flow.instances[sid])
        self.emit("approval_resolved", step=sid, decision="approved", by=by, accepted_defaults=accepted, text=None)
        self._send_problems(sid)
        self.save()

    def answer(self, qid: str, answer: str, *, by: str = "you", hint: str | None = None,
               kind: str | None = None) -> Question:
        """Answer a question. A question of a stopped fix loop takes `fix_again` (with `hint`), `other_input`
        (with the `kind` a step answers, and `hint` as the content) or `accept`."""
        q = self.decisions.get(qid)
        if q is None:
            raise EngineError(f"no question {qid}")
        if q.status != "open":
            raise EngineError(f"{qid} is {q.status}")
        if q.problem is not None:
            self._answer_loop(q, answer, by, hint, kind)
        else:
            self._answer_plain(q, answer, by)
        self.emit("question_answered", step=q.step, id=q.id, status=q.status, by=by)
        st = self.state.step(q.step)
        if st.loop.pending and self.gate(q.step) == "auto" and not self.decisions.open_of(q.step, blocking=True):
            self._send_problems(q.step)
        self.save()
        return q

    def _owner(self, q: Question) -> str:
        if q.kind == "design_choice":
            return q.step
        owner = self.flow.answers.get(q.kind)
        if owner is None or owner not in self.flow.upstream(q.step):
            return q.step
        if self.state.step(owner).origin == "user":
            return q.step
        return owner

    def _answer_plain(self, q: Question, answer: str, by: str) -> None:
        is_default = q.default is not None and str(answer) == str(q.default)
        self.decisions.settle(q, "defaulted" if is_default and by == "auto" else "answered", answer, by)
        owner = self._owner(q)
        q.owner = owner
        text = f"{q.text} → {answer}"
        if owner != q.step:  # the owner updates, then the step that asked runs again on its new output
            self._add_request(owner, "decision", text, key=q.key, kind=q.kind, question=q.id)
            self._add_request(q.step, "decision", text, key=q.key, kind=q.kind, question=q.id)
        elif not is_default:  # its own default is already in its output
            self._add_request(q.step, "decision", text, key=q.key, kind=q.kind, question=q.id)
        self._reset_round(owner)

    def _answer_loop(self, q: Question, answer: str, by: str, hint: str | None, kind: str | None) -> None:
        p = q.problem
        checker = p["checker"]
        lp = self.state.step(checker).loop
        if answer == "fix_again":
            text = f"{p['text']}\nHint: {hint}" if hint else p["text"]
            self._add_request(p["receiver"], "fix", text, unit=p["unit"], kind=p["kind"], key=p["key"])
            lp.round, lp.stopped, lp.last = 0, False, None
        elif answer == "other_input":
            owner = self.flow.answers.get(kind or "")
            if owner is None or owner not in self.flow.upstream(checker):
                raise EngineError(f"no step before {checker} answers `{kind}`")
            self._add_request(owner, "decision", hint or p["text"], kind=kind, key=q.key, question=q.id)
            lp.round, lp.stopped, lp.last = 0, False, None
        elif answer == "accept":
            ident = [p["kind"], str(p["unit"]), str(p["key"])]
            if ident not in lp.accepted:
                lp.accepted.append(ident)
        else:
            raise EngineError("the answer is `fix_again`, `other_input` or `accept`")
        self.decisions.settle(q, "defaulted" if by == "auto" else "answered", answer, by)
        # every problem of the stopped loop accepted: the checking step passes
        if lp.stopped and not [x for x in self.decisions.open_of(checker) if x.problem is not None]:
            self._loop_pass(checker)

    def review(self, sid: str, artifact: str, item: str, *, confirm: bool = True, text: str = "") -> None:
        st = self.state.step(sid)
        items = st.reviews.get(artifact) or {}
        if item not in items:
            raise EngineError(f"{sid}: no review item `{item}` in `{artifact}`")
        if confirm:
            items[item]["status"] = "confirmed"
        else:
            items[item]["status"] = "change_requested"
            self.request_change(sid, f"[{artifact}: {item}] {text}")
        self.save()

    def reset(self, sid: str, *, only: bool = False) -> list[str]:
        if self.running:
            raise EngineError("a reset is refused while a run is going on")
        if sid not in self.flow.instances:
            raise EngineError(f"no step `{sid}`")
        targets = [sid] if only else [s for s in self.flow.order() if s == sid or s in self.flow.downstream(sid)]
        bdir = self.project.backups / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-reset-{sid}"
        for s in targets:
            inst = self.flow.instances[s]
            st = self.state.step(s)
            if st.origin != "user":
                files = self._output_files(inst, generated_only=True)
                backup(files, self.root, bdir)
                for f in files:
                    f.unlink(missing_ok=True)
            for d in (self.project.work_dir(s), self.project.session_dir(s), self.project.cache_dir(s),
                      self.project.loop_dir(s)):
                shutil.rmtree(d, ignore_errors=True)
            cost = st.cost_usd
            self.state.steps[s] = StepState(cost_usd=cost)
            for o in inst.outputs:
                if self.state.artifacts.get(o.artifact, {}).get("by") == s:
                    del self.state.artifacts[o.artifact]
            self.decisions.clear_step(s)
        self.save()
        return targets

    # -- definitions ------------------------------------------------------------------------------

    def definition_changes(self) -> list[dict]:
        out = []
        for sid, inst in self.flow.instances.items():
            st = self.state.steps.get(sid)
            if st is None or not st.ran:
                continue
            d = st.definition or {}
            if not d.get("hash") or d["hash"] == inst.definition_hash or d.get("later") == inst.definition_hash:
                continue
            old = d.get("files") or {}
            files = sorted(k for k in set(old) | set(inst.definition_files) if old.get(k) != inst.definition_files.get(k))
            out.append({"step": sid, "files": files, "old_version": d.get("version"), "new_version": inst.version})
        return out

    def check_definitions(self) -> list[dict]:
        changed = self.definition_changes()
        if changed:
            self.emit("definition_changed", steps=changed)
        return changed

    def definition_later(self, steps: list[str]) -> None:
        for sid in steps:
            st = self.state.step(sid)
            st.definition = {**(st.definition or {}), "later": self.flow.instances[sid].definition_hash}
        self.save()

    # -- outcome ----------------------------------------------------------------------------------

    def _outcomes(self, stages: list[str], in_scope: set[str]) -> list[StageOutcome]:
        out = []
        for name in stages:
            steps = [s for s in next(st for st in self.flow.stages if st.name == name).steps if s in in_scope]
            statuses = {s: self.status(s) for s in steps}
            cancelled = [s for s in steps if s in self._cancelled]
            failed = [s for s, x in statuses.items() if x.result == "failed"]
            waiting = [s for s, x in statuses.items()
                       if x.blocking_questions or (x.approval and x.approval.status == "waiting" and x.result == "done")]
            if cancelled:
                out.append(StageOutcome(name, "cancelled", f"{cancelled[0]}: stopped"))
            elif failed:
                out.append(StageOutcome(name, "failed", f"{failed[0]}: {statuses[failed[0]].reason}"))
            elif waiting:
                s = waiting[0]
                what = "an answer" if statuses[s].blocking_questions else "approval"
                out.append(StageOutcome(name, "waiting", f"{s}: waiting for {what}"))
            elif all(x.result == "done" for x in statuses.values()):
                out.append(StageOutcome(name, "complete"))
            else:
                out.append(StageOutcome(name, "blocked", self._blocked_reason(steps, statuses)))
        return out

    def _blocked_reason(self, steps: list[str], statuses: dict[str, StepStatus]) -> str:
        if self._cost_reached():
            return "cost limit reached"
        for s in steps:
            if statuses[s].result == "missing_input":
                return f"{s}: {statuses[s].reason}"
        for s in steps:
            if statuses[s].result in ("pending", "stale"):
                waits = sorted(d for d in self.flow.upstream(s) if not self.settled_for_feed(d))
                if waits:
                    stages = []
                    for d in waits:
                        n = self.flow.stage_of(d).name
                        if n not in stages:
                            stages.append(n)
                    own = self.flow.stage_of(s).name
                    names = [n for n in stages if n != own] or [waits[0]]
                    return f"waits for {', '.join(names)}"
        return "not started"

    # -- cost -----------------------------------------------------------------------------------

    def reset_cost(self) -> None:
        self.state.cost_resets.append({"at": now(), "total_usd": round(self.state.cost_usd, 4),
                                       "steps": {s: round(st.cost_usd, 4) for s, st in self.state.steps.items()}})
        self.state.cost_resets[-1]["assistant_usd"] = round(self.state.assistant_cost_usd, 4)
        self.state.cost_usd = 0.0
        self.state.assistant_cost_usd = 0.0
        for st in self.state.steps.values():
            st.cost_usd = 0.0
        self.save()
