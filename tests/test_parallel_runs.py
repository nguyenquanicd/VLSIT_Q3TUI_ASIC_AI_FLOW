"""Runs of several flows in one project folder (docs/spec/pipeline.md "Runs of several flows"): `r` in dv, then fpga, then sanity. One run per
flow, one state file merged per step, a step two runs share runs once, an input another run changes keeps a step stale. Code-only step kinds: a
design flow (spec → rtl, each applying its change requests to its file) and checking flows that check the RTL and, when it lacks something, hand
a fix to the design flow within the run (as the dv triage does)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import anyio
import pytest

from q3tui import flows
from q3tui.core.project import Project
from q3tui.pipeline.base import StepContext, StepDef, StepFailed
from q3tui.pipeline.engine import Engine


class TSpec(StepDef):
    """Design: spec/intent.md → spec/spec.md; a change request becomes a line of it."""

    title = "T spec"

    def inputs(self, engine):
        return [engine.project.root / "spec" / "intent.md"]

    def outputs(self, engine):
        p = engine.project.root / "spec" / "spec.md"
        return [p] if p.is_file() else []

    async def run(self, ctx: StepContext) -> None:
        p = ctx.project.root / "spec" / "spec.md"
        lines = p.read_text().splitlines() if p.is_file() else [(ctx.project.root / "spec" / "intent.md").read_text().strip()]
        p.write_text("\n".join([*lines, *(f"decision: {f}" for f in ctx.feedback)]) + "\n")


class TRtl(StepDef):
    """Design: src/rtl/top.sv from the spec; a change request `[rtl:top] X` becomes a `// fix: X` line (kept across runs)."""

    title = "T rtl"

    def inputs(self, engine):
        return [engine.project.root / "spec" / "spec.md"]

    def outputs(self, engine):
        p = engine.project.root / "src" / "rtl" / "top.sv"
        return [p] if p.is_file() else []

    async def run(self, ctx: StepContext) -> None:
        p = ctx.project.root / "src" / "rtl" / "top.sv"
        p.parent.mkdir(parents=True, exist_ok=True)
        fixes = [x for x in p.read_text().splitlines() if x.startswith("// fix:")] if p.is_file() else []
        fixes += [f"// fix: {f.split('] ', 1)[-1]}" for f in ctx.feedback if f"// fix: {f.split('] ', 1)[-1]}" not in fixes]
        p.write_text("module top;\n" + "".join(f"{x}\n" for x in fixes) + "endmodule\n")


class TCheck(StepDef):
    """A check of the RTL. options: need (a fix the RTL must have: handed to the design flow within the run), sleep."""

    title = "T check"

    def inputs(self, engine):
        return [engine.project.root / "src" / "rtl" / "top.sv"]

    def outputs(self, engine):
        p = engine.project.root / "results" / f"{self.name}.txt"
        return [p] if p.is_file() else []

    async def run(self, ctx: StepContext) -> None:
        o, root, eng = self.options, ctx.project.root, ctx.engine
        await anyio.sleep(float(o.get("sleep", 0)))
        meta = eng.state.step_meta.setdefault(self.name, {})
        rounds = int(meta.get("rounds", 0))
        rtl = (root / "src" / "rtl" / "top.sv").read_text()
        need = o.get("need")
        if need and f"// fix: {need}" not in rtl:
            if rounds >= 3:
                raise StepFailed(f"the RTL still lacks {need}")
            eng.save()  # (as the dv triage: the design flow's engine queues the fix, this one reads it back, the run runs that flow)
            Engine(ctx.project, flow=flows.load_flow("design", root)).request_change("rtl", f"[rtl:top] {need}")
            eng.reload()
            eng.hand_to_flow(self.name, "design")
            eng.state.step_meta[self.name]["rounds"] = rounds + 1
            return
        (root / "results").mkdir(exist_ok=True)
        (root / "results" / f"{self.name}.txt").write_text(f"pass on {rtl.count('// fix:')} fix(es)\n")


@pytest.fixture(autouse=True)
def _kinds():
    from q3tui.steps import KINDS, register_kind

    names = {"t_spec": "TSpec", "t_rtl": "TRtl", "t_check": "TCheck"}
    for k, cls in names.items():
        register_kind(k, f"tests.test_parallel_runs:{cls}")
    yield
    for k in names:
        KINDS.pop(k, None)


SPEC = "- {id: spec, kind: t_spec}\n"


def _write_flow(root: Path, name: str, steps: str) -> None:
    (root / "flows").mkdir(exist_ok=True)
    (root / "flows" / f"{name}.yaml").write_text(f"name: {name}\nsteps:\n" + "".join(f"  {s}\n" for s in steps.splitlines() if s.strip()))


def _project(tmp_path: Path) -> Project:
    root = tmp_path / "proj"
    (root / "spec").mkdir(parents=True)
    (root / "spec" / "intent.md").write_text("a block\n")
    _write_flow(root, "design", SPEC + "- {id: rtl, kind: t_rtl, deps: [spec]}")
    _write_flow(root, "lb", SPEC + "- {id: check_b, kind: t_check, deps: [spec], options: {need: B, sleep: 0.3}}")
    _write_flow(root, "lc", SPEC + "- {id: check_c, kind: t_check, deps: [spec], options: {sleep: 0.3}}")
    (root / "q3tui.yaml").write_text("pipeline: {flow: design, design_flows: [design]}\n")
    project = Project.open(root)
    assert anyio.run(lambda: Engine(project, flow=flows.load_flow("design", root)).run(yes=True)) == "complete"
    return project


@pytest.fixture
def other_run():
    """A live process standing in for a run of another flow: `lock(flow)` writes its lock."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

    def lock(project, flow: str, phase: str = "running") -> int:
        project.ensure_state_dir()
        (project.state_dir / f"run.{flow}.lock").write_text(json.dumps({"pid": p.pid, "started": "2026-01-01T00:00:00", "flow": flow, "phase": phase}))
        return p.pid

    lock.process = p
    yield lock
    p.kill()
    p.wait()


def _flow(project, name):
    return flows.load_flow(name, project.root)


def test_the_runs_of_two_flows_share_the_state_file(tmp_path, other_run):
    project = _project(tmp_path)
    cost0 = Engine(project).state.total_cost_usd
    a, b = Engine(project, flow=_flow(project, "lb")), Engine(project, flow=_flow(project, "lc"))
    a.state.step_meta["check_b"] = {"x": 1}
    a.state.feedback.setdefault("rtl", []).append("[rtl:top] from lb")
    a.state.total_cost_usd += 1.0
    b.state.step_meta["check_c"] = {"y": 2}
    b.state.feedback.setdefault("rtl", []).append("[rtl:top] from lc")
    b.state.total_cost_usd += 2.0
    a.save()
    b.save()  # (b never read a's changes: per step, each keeps what it changed)
    st = Engine(project).state
    assert st.step_meta["check_b"] == {"x": 1} and st.step_meta["check_c"] == {"y": 2}
    assert st.feedback["rtl"] == ["[rtl:top] from lb", "[rtl:top] from lc"] and st.total_cost_usd == pytest.approx(cost0 + 3.0)
    a.state.feedback["rtl"].remove("[rtl:top] from lb")  # (a consumed its own request: b's stays)
    a.save()
    assert Engine(project).state.feedback["rtl"] == ["[rtl:top] from lc"]
    # one run per flow: a run of lb elsewhere — a TUI on lb only watches it, lc saves and runs beside it
    pid = other_run(project, "lb")
    a2, b2 = Engine(project, flow=_flow(project, "lb")), Engine(project, flow=_flow(project, "lc"))
    assert a2.other_run()["pid"] == pid and b2.other_run() is None and [r["flow"] for r in b2.other_runs()] == ["lb"]
    a2.state.step_meta["check_b"] = {"x": 9}
    a2.save()
    b2.state.step_meta["check_c"] = {"y": 3}
    b2.save()
    st = Engine(project).state
    assert st.step_meta["check_b"] == {"x": 1} and st.step_meta["check_c"] == {"y": 3}
    assert anyio.run(lambda: a2.run(yes=True)) == "blocked"


def test_a_step_another_run_executes_is_waited_for(tmp_path, other_run, monkeypatch):
    monkeypatch.setattr(Engine, "WAIT_S", 0.05)
    project = _project(tmp_path)
    (project.root / "spec" / "intent.md").write_text("a block, v2\n")  # (spec is out of date for every flow that has it)
    eng0 = Engine(project, flow=_flow(project, "design"))
    rec = eng0.state.step("spec")
    rec.status, rec.pid = "running", other_run.process.pid  # another process runs it
    eng0.save()
    seen = []
    eng = Engine(project, flow=_flow(project, "lc"))
    eng.bus.subscribe(seen.append)
    out = {}

    async def main():
        async def run():
            out["outcome"] = await eng.run(yes=True)

        async with anyio.create_task_group() as tg:
            tg.start_soon(run)
            await anyio.sleep(0.5)
            out["waited"] = any("spec is running in another run: waiting" in str(e.data.get("message")) for e in seen)
            out["spec_then"] = Engine(project).state.steps["spec"].pid
            other_run.process.kill()  # (that run ends; here it was killed: the step is interrupted, this run runs it itself)

    anyio.run(main)
    assert out["waited"] and out["spec_then"] == other_run.process.pid and out["outcome"] == "complete"
    st = Engine(project).state.steps["spec"]
    assert st.status == "done" and st.pid is None


def test_an_input_another_run_changes_while_a_step_runs_keeps_it_stale(tmp_path, other_run):
    project = _project(tmp_path)
    other_run(project, "lb")  # (another flow's run goes on meanwhile)
    eng = Engine(project, flow=_flow(project, "lc"))
    seen = []
    eng.bus.subscribe(seen.append)

    async def main():
        async def edit():
            await anyio.sleep(0.15)  # (check_c sleeps 0.3: its RTL changes under it)
            (project.root / "src" / "rtl" / "top.sv").write_text("module top;\n// fix: elsewhere\nendmodule\n")

        async with anyio.create_task_group() as tg:
            tg.start_soon(edit)
            assert await eng.run(yes=True) == "complete"

    anyio.run(main)
    assert any("src/rtl/top.sv changed in another run while check_c ran" in str(e.data.get("message")) for e in seen)
    views = {v.name: v.status for v in Engine(project, flow=_flow(project, "lc")).status()}
    assert views["check_c"] == "stale"
