"""spec/engine.md: order, staleness, updates, gates, questions, the fix loop, operations — with fake steps."""

import asyncio
import json
from pathlib import Path

import pytest

from q3tui.config import ConfigLayers
from q3tui.engine import Engine, EngineError, Ops, Scope, StepError
from q3tui.engine.events import read_events
from q3tui.flowdef import Lookup, load_flow
from q3tui.workspace import Project


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def step_md(home: Path, name: str, front: str = "") -> None:
    write(home / f"steps/{name}/STEP.md", f"---\nname: {name}\ndescription: step {name}\nversion: 1.0.0\n{front}---\n")


class Fake:
    """A step's code: `run` is an async function of ctx; `checks` the `check_<name>` methods."""

    def __init__(self, run=None, checks=None):
        self._run = run
        self.checks = checks or {}
        self.calls: list = []
        self.approved = 0

    async def run(self, ctx):
        self.calls.append(ctx.changes)
        if self._run:
            await self._run(ctx)

    def check(self, name, ctx):
        return self.checks[name](ctx)

    def on_approve(self, ctx):
        self.approved += 1


def writer(name: str, text: str = "v1"):
    async def run(ctx):
        out = ctx.outputs[name]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    return run


class World:
    """A home with flow files, a project, and the fake code of each step."""

    def __init__(self, tmp: Path, stages: dict[str, list], steps: dict[str, str], *, overrides: str = "",
                 config: str = ""):
        self.home = tmp / "home"
        self.project = Project.open(tmp / "proj")
        stage_list = ", ".join(stages)
        write(self.home / "flows/f/FLOW.md",
              f"---\nname: f\ndescription: a flow\nversion: 1.0.0\nstages: [{stage_list}]\n{overrides}---\n")
        for st, members in stages.items():
            write(self.home / f"stages/{st}/STAGE.md",
                  f"---\nname: {st}\ndescription: s\nversion: 1.0.0\nsteps: [{', '.join(members)}]\n---\n")
        for name, front in steps.items():
            step_md(self.home, name, front)
        if config:
            write(self.project.config_file, config)
        self.code: dict[str, Fake] = {n: Fake(writer(n)) for n in steps}
        self.engine: Engine | None = None

    def open(self) -> Engine:
        cfg = ConfigLayers(None, self.project.config_file)
        lookup = Lookup(self.project.q3, self.home)
        flow = load_flow("f", lookup, cfg)
        assert flow.ok, [str(p) for p in flow.problems]
        self.engine = Engine(self.project, flow, cfg, lookup, code_for=lambda inst: self.code[inst.step])
        self.ops = Ops(self.engine, home=self.home)
        return self.engine

    def file(self, rel: str) -> Path:
        return self.project.root / rel

    def kinds(self, kind: str) -> list[dict]:
        return [e for e in read_events(self.project.events_file) if e["kind"] == kind]

    def started(self) -> list[str]:
        return [e["step"] for e in self.kinds("step_started")]


def chain(tmp, a_front="", b_front="", **kw) -> World:
    return World(tmp, {"s": ["a", "b"]}, {
        "a": "outputs:\n  - {artifact: a, path: out/a.txt}\n" + a_front,
        "b": "inputs:\n  - {artifact: a}\noutputs:\n  - {artifact: b, path: out/b.txt}\n" + b_front,
    }, **kw)


def outcome(outcomes) -> dict:
    return {o.stage: (o.outcome, o.reason) for o in outcomes}


# -- order, staleness, updates ------------------------------------------------------------------------


async def test_runs_like_make(tmp_path):
    w = chain(tmp_path)
    eng = w.open()
    res = await eng.run()
    assert outcome(res) == {"s": ("complete", "")}
    assert w.started() == ["a", "b"]
    assert eng.status("b").display == "done"
    await eng.run()
    assert w.started() == ["a", "b"]  # nothing missing or stale: nothing runs
    w.file("out/a.txt").write_text("by hand")
    assert eng.status("a").edited == ["a"] and eng.status("a").display == "done"
    assert eng.status("b").display == "stale"
    await eng.run()
    assert w.started() == ["a", "b", "b"]
    changes = w.code["b"].calls[-1]
    assert not changes.first_run and changes.inputs == [{"artifact": "a", "change": "changed"}]


async def test_param_change_and_request_make_stale(tmp_path):
    w = chain(tmp_path, a_front="params:\n  depth: {type: int, default: 2}\n  turns: {type: int, default: 3, affects_result: false}\n")
    eng = w.open()
    await eng.run()
    write(w.project.config_file, "steps:\n  a:\n    params: {turns: 9}\n")
    eng = w.open()
    assert eng.status("a").display == "done"
    write(w.project.config_file, "steps:\n  a:\n    params: {depth: 4}\n")
    eng = w.open()
    assert eng.status("a").display == "stale"
    await eng.run()
    assert w.code["a"].calls[-1].params == [{"name": "depth", "old": 2, "new": 4}]
    eng.request_change("a", "rename the port")
    assert eng.status("a").display == "stale"
    await eng.run()
    assert w.code["a"].calls[-1].requests[0]["text"] == "rename the port"
    assert eng.status("a").display == "done"


async def test_update_step_is_not_stale_by_its_own_write(tmp_path):
    w = World(tmp_path, {"s": ["a", "fmt", "b"]}, {
        "a": "outputs:\n  - {artifact: a, path: out/a.txt}\n",
        "fmt": "inputs:\n  - {artifact: a}\noutputs:\n  - {artifact: a, mode: update}\n",
        "b": "inputs:\n  - {artifact: a}\noutputs:\n  - {artifact: b, path: out/b.txt}\n",
    })

    async def fmt(ctx):
        f = ctx.inputs["a"][0]
        f.write_text(f.read_text().upper())

    w.code["fmt"] = Fake(fmt)
    eng = w.open()
    await eng.run()
    assert w.file("out/a.txt").read_text() == "V1"
    assert [eng.status(s).display for s in ("a", "fmt", "b")] == ["done", "done", "done"]
    assert eng.status("a").edited == []


# -- results that stop a chain --------------------------------------------------------------------------


async def test_failed_step_blocks_its_chain(tmp_path):
    w = chain(tmp_path)

    async def boom(ctx):
        raise RuntimeError("no top module")

    w.code["a"] = Fake(boom)
    eng = w.open()
    res = await eng.run()
    assert outcome(res) == {"s": ("failed", "a: no top module")}
    assert eng.status("a").display == "failed" and eng.status("b").display == "pending"


async def test_step_error_for_an_undeclared_kind(tmp_path):
    w = chain(tmp_path)

    async def asks(ctx):
        ctx.ask("spec_gap", "x.y", "?", "1")

    w.code["a"] = Fake(asks)
    eng = w.open()
    await eng.run()
    assert "question kind `spec_gap` is not in the step's `questions`" in eng.status("a").reason


async def test_missing_input_and_user_file(tmp_path):
    w = World(tmp_path, {"s": ["spec", "parse"]}, {
        "spec": "inputs:\n  - {artifact: intent, path: spec/intent.md}\n"
                "outputs:\n  - {artifact: spec, path: spec/spec.md, user_provided: true}\n",
        "parse": "inputs:\n  - {artifact: spec}\noutputs:\n  - {artifact: parse, path: out/p.json}\n",
    })
    eng = w.open()
    assert eng.status("spec").display == "missing_input"
    assert eng.status("spec").missing == ["the input `intent` (spec/intent.md) does not exist"]
    res = await eng.run()
    assert outcome(res)["s"][0] == "blocked"
    write(w.file("spec/spec.md"), "my spec")
    res = await eng.run()
    assert outcome(res) == {"s": ("complete", "")}
    st = eng.status("spec")
    assert st.origin == "user" and st.display == "approved"
    assert w.started() == ["parse"]
    assert w.kinds("step_skipped")[0]["reason"] == "user"


async def test_pass_checks(tmp_path):
    w = chain(tmp_path, a_front="pass:\n  - {check: \"contains a ^v2\"}\n  - {check: \"code ready\", on_fail: warn}\n")
    w.code["a"].checks = {"ready": lambda ctx: "not ready"}
    eng = w.open()
    await eng.run()
    assert eng.status("a").display == "failed"
    assert "contains a ^v2" in eng.status("a").reason
    assert any("not ready" in e["message"] for e in w.kinds("warning"))


async def test_schema_is_checked(tmp_path):
    w = chain(tmp_path, a_front="")
    write(w.home / "steps/a/STEP.md", "---\nname: a\ndescription: d\nversion: 1.0.0\n"
          "outputs:\n  - {artifact: a, path: out/a.json, schema: a.schema.json}\n---\n")
    write(w.home / "steps/a/a.schema.json", json.dumps({"type": "object", "required": ["ok"]}))
    w.code["a"] = Fake(writer("a", "{}"))
    eng = w.open()
    await eng.run()
    assert "does not match a.schema.json" in eng.status("a").reason


# -- gates ----------------------------------------------------------------------------------------------


async def test_manual_gate_stops_until_approved(tmp_path):
    w = chain(tmp_path, a_front="gate: manual\n")
    eng = w.open()
    res = await eng.run()
    assert outcome(res) == {"s": ("waiting", "a: waiting for approval")}
    assert eng.status("a").display == "approval waiting" and w.started() == ["a"]
    eng.approve("a")
    assert eng.status("a").display == "approved" and w.code["a"].approved == 1
    await eng.run()
    assert w.started() == ["a", "b"]
    with pytest.raises(EngineError):
        eng.approve("a")


async def test_unchanged_result_keeps_approval(tmp_path):
    w = chain(tmp_path, a_front="gate: manual\n")
    eng = w.open()
    await eng.run()
    eng.approve("a")
    eng.request_change("a", "nothing really")
    await eng.run(Scope(only="a"))
    assert eng.status("a").display == "approved"  # same outputs: approval kept
    w.code["a"] = Fake(writer("a", "v2"))
    eng.request_change("a", "change it")
    await eng.run(Scope(only="a"))
    assert eng.status("a").display == "approval waiting"


async def test_config_gate_wins(tmp_path):
    w = chain(tmp_path, a_front="gate: manual\n", config="pipeline: {gate_mode: unattended}\n")
    eng = w.open()
    assert eng.gate("a") == "unattended"
    w.ops.gate_mode("manual", "a")
    assert eng.gate("a") == "manual"
    w.ops.gate_mode(None, "a")
    assert eng.gate("a") == "unattended"


async def test_review_items_block_manual_approval(tmp_path):
    w = chain(tmp_path, a_front="gate: manual\n")
    write(w.home / "steps/a/STEP.md", "---\nname: a\ndescription: d\nversion: 1.0.0\ngate: manual\n"
          "outputs:\n  - {artifact: a, path: out/a.md, view: {kind: sections, by: marker, review: true}}\n---\n")
    w.code["a"] = Fake(writer("a", "<!-- section: intro -->\nhello\n<!-- section: ports -->\nclk\n"))
    eng = w.open()
    await eng.run()
    assert eng.status("a").pending_reviews == 2
    with pytest.raises(EngineError, match="not reviewed"):
        eng.approve("a")
    eng.review("a", "a", "intro")
    eng.review("a", "a", "ports")
    eng.approve("a")
    assert eng.status("a").display == "approved"


# -- questions -----------------------------------------------------------------------------------------


async def test_blocking_question_under_auto(tmp_path):
    w = chain(tmp_path)

    async def asks(ctx):
        await writer("a")(ctx)
        ctx.ask("design_choice", "fifo.depth", "Depth?", "4", options=["4", "8"], blocking=True)
        ctx.ask("design_choice", "fifo.name", "Name?", "f")

    w.code["a"] = Fake(asks)
    eng = w.open()
    res = await eng.run()
    assert outcome(res) == {"s": ("waiting", "a: waiting for an answer")}
    st = eng.status("a")
    assert st.display == "question waiting" and st.open_questions == 1
    q = eng.decisions.by_key("fifo.name")
    assert q.status == "defaulted" and q.by == "auto"
    eng.answer("a-Q1", "8")
    assert eng.status("a").display == "stale"  # the decision goes back to the step that asked
    w.code["a"] = Fake(writer("a"))
    await eng.run()
    assert w.code["a"].calls[-1].requests[0]["source"] == "decision"
    assert eng.status("b").display == "done"


async def test_settled_key_is_not_asked_again(tmp_path):
    w = chain(tmp_path, a_front="gate: unattended\n")
    seen = []

    async def asks(ctx):
        await writer("a")(ctx)
        seen.append(ctx.ask("design_choice", "k", "?", "x", blocking=True))

    w.code["a"] = Fake(asks)
    eng = w.open()
    await eng.run()
    assert eng.decisions.by_key("k").status == "defaulted"
    eng.request_change("a", "again")
    await eng.run()
    assert seen == [None, "x"] and len(eng.decisions.questions) == 1


async def test_answer_goes_to_the_owner_and_rebase(tmp_path):
    w = World(tmp_path, {"s": ["arch", "rtl"]}, {
        "arch": "outputs:\n  - {artifact: arch, path: out/arch.md}\nanswers: [arch_gap]\n",
        "rtl": "inputs:\n  - {artifact: arch}\noutputs:\n  - {artifact: rtl, path: out/rtl.sv}\n"
               "questions: [arch_gap]\npass:\n  - {check: \"exists rtl\"}\n",
    })
    asked = {"n": 0}

    async def rtl(ctx):
        await writer("rtl")(ctx)
        if asked["n"] == 0:
            ctx.ask("arch_gap", "reset.sync", "Sync reset?", "yes", blocking=True)
        asked["n"] += 1

    w.code["rtl"] = Fake(rtl)
    eng = w.open()
    await eng.run()
    eng.answer("rtl-Q1", "yes")  # the default: rtl's output already holds it
    q = eng.decisions.get("rtl-Q1")
    assert q.owner == "arch" and q.status == "answered"
    w.code["arch"] = Fake(writer("arch", "v2"))
    await eng.run()
    assert w.started() == ["arch", "rtl", "arch"]  # rtl is rebased, not run again
    assert w.kinds("step_skipped")[-1] == {**w.kinds("step_skipped")[-1], "step": "rtl", "reason": "up_to_date"}
    assert eng.status("rtl").display == "done"


# -- the fix loop ----------------------------------------------------------------------------------------


def loop_world(tmp, *, config="", checker_gate="auto") -> World:
    return World(tmp, {"s": ["rtl", "lint"]}, {
        "rtl": "outputs:\n  - {artifact: rtl, path: out/rtl.sv}\nreceives: [rtl_fix]\n",
        "lint": f"inputs:\n  - {{artifact: rtl}}\noutputs:\n  - {{artifact: lint, path: out/lint.json}}\n"
                f"handback: [rtl_fix]\ngate: {checker_gate}\n",
    }, config=config)


def rtl_that_fixes(times: int):
    state = {"n": 0}

    async def run(ctx):
        fixes = [r for r in ctx.changes.requests if r["source"] == "fix"]
        if fixes:
            state["n"] += 1
        out = ctx.outputs["rtl"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("ok" if state["n"] >= times else f"bad{state['n']}")
    return run


def lint(problem_key=lambda text: "always"):
    async def run(ctx):
        text = ctx.inputs["rtl"][0].read_text()
        ctx.outputs["lint"].write_text("{}")
        if text != "ok":
            ctx.handback("rtl_fix", "top", problem_key(text), f"lint error in {text}")
    return run


async def test_loop_passes(tmp_path):
    w = loop_world(tmp_path)
    w.code["rtl"] = Fake(rtl_that_fixes(1))
    w.code["lint"] = Fake(lint())
    eng = w.open()
    res = await eng.run()
    assert outcome(res) == {"s": ("complete", "")}
    assert w.started() == ["rtl", "lint", "rtl", "lint"]
    assert [e["round"] for e in w.kinds("loop_round")] == [1]
    assert w.kinds("loop_stopped")[-1]["reason"] == "pass"
    assert w.code["rtl"].calls[1].requests[0] == {"source": "fix", "text": "lint error in bad0", "unit": "top",
                                                  "kind": "rtl_fix", "key": "always"}


async def test_loop_stops_on_the_same_problems_and_restores_the_best(tmp_path):
    w = loop_world(tmp_path)
    w.code["rtl"] = Fake(rtl_that_fixes(99))
    w.code["lint"] = Fake(lint())
    eng = w.open()
    res = await eng.run()
    assert w.kinds("loop_stopped")[-1]["reason"] == "same_problems"
    assert outcome(res) == {"s": ("waiting", "lint: waiting for an answer")}
    assert w.file("out/rtl.sv").read_text() == "bad1"  # the latest of the equal best rounds
    assert eng.status("rtl").display == "done" and eng.status("lint").display == "question waiting"
    q = eng.decisions.open_of("lint")[0]
    assert [o["id"] for o in q.options] == ["fix_again", "other_input", "accept"]
    eng.answer(q.id, "accept")
    assert w.kinds("loop_stopped")[-1]["reason"] == "pass"
    assert eng.status("lint").display == "done"


async def test_loop_stops_at_max_rounds(tmp_path):
    w = loop_world(tmp_path, config="pipeline: {max_fix_rounds: 2}\n")
    w.code["rtl"] = Fake(rtl_that_fixes(99))
    w.code["lint"] = Fake(lint(problem_key=lambda text: text))  # a new problem every round
    eng = w.open()
    await eng.run()
    assert [e["round"] for e in w.kinds("loop_round")] == [1, 2]
    assert w.kinds("loop_stopped")[-1]["reason"] == "max_rounds"


async def test_loop_fix_again_with_a_hint(tmp_path):
    w = loop_world(tmp_path, config="pipeline: {max_fix_rounds: 1}\n")
    w.code["rtl"] = Fake(rtl_that_fixes(2))
    w.code["lint"] = Fake(lint())
    eng = w.open()
    await eng.run()
    q = eng.decisions.open_of("lint")[0]
    eng.answer(q.id, "fix_again", hint="look at the reset")
    assert "Hint: look at the reset" in eng.state.step("rtl").pending_requests()[0].text
    await eng.run()
    assert w.kinds("loop_stopped")[-1]["reason"] == "pass"


async def test_loop_unattended_accepts(tmp_path):
    w = loop_world(tmp_path, config="pipeline: {max_fix_rounds: 1}\n", checker_gate="unattended")
    w.code["rtl"] = Fake(rtl_that_fixes(99))
    w.code["lint"] = Fake(lint())
    eng = w.open()
    res = await eng.run()
    assert outcome(res) == {"s": ("complete", "")}
    q = eng.decisions.questions[0]
    assert q.status == "defaulted" and q.answer == "accept" and q.by == "auto"


async def test_manual_checker_sends_on_approval(tmp_path):
    w = loop_world(tmp_path, checker_gate="manual")
    w.code["rtl"] = Fake(rtl_that_fixes(1))
    w.code["lint"] = Fake(lint())
    eng = w.open()
    await eng.run()
    assert eng.status("lint").display == "approval waiting" and not w.kinds("loop_round")
    eng.approve("lint")
    assert eng.status("rtl").display == "stale"
    await eng.run()
    assert eng.status("lint").display == "approved"  # the same report as before: its approval is kept
    assert w.kinds("loop_stopped")[-1]["reason"] == "pass"


# -- operations ----------------------------------------------------------------------------------------


async def test_scope(tmp_path):
    w = World(tmp_path, {"s": ["a", "b"], "t": ["c"]}, {
        "a": "outputs:\n  - {artifact: a, path: out/a.txt}\n",
        "b": "outputs:\n  - {artifact: b, path: out/b.txt}\n",
        "c": "inputs:\n  - {artifact: b}\noutputs:\n  - {artifact: c, path: out/c.txt}\n",
    })
    eng = w.open()
    assert eng.scope_steps(Scope(from_="b")) == ["b", "c"]
    assert eng.scope_steps(Scope(to="c")) == ["a", "b", "c"]
    assert eng.scope_steps(Scope(stage="t")) == ["c"]
    with pytest.raises(EngineError, match="not ready: a, b"):
        await eng.run(Scope(only="c"))
    await eng.run(Scope(stage="s"))
    assert w.started() == ["a", "b"]
    await eng.run(rerun=["a"])
    assert w.started() == ["a", "b", "a", "c"]


async def test_reset_deletes_what_q3tui_wrote(tmp_path):
    w = chain(tmp_path)
    eng = w.open()
    await eng.run()
    targets = eng.reset("a")
    assert targets == ["a", "b"]
    assert not w.file("out/a.txt").exists() and not w.file("out/b.txt").exists()
    assert eng.status("a").display == "pending"
    assert list(w.project.backups.glob("*-reset-a/files/out/a.txt"))


async def test_seed_is_never_overwritten(tmp_path):
    w = chain(tmp_path)
    write(w.home / "steps/a/STEP.md", "---\nname: a\ndescription: d\nversion: 1.0.0\noutputs:\n"
          "  - {artifact: a, path: out/a.txt}\n  - {artifact: waivers, path: out/w.json, mode: seed}\n---\n")

    async def run(ctx):
        await writer("a")(ctx)
        ctx.outputs["waivers"].write_text("generated")

    w.code["a"] = Fake(run)
    eng = w.open()
    await eng.run()
    w.file("out/w.json").write_text("mine")
    assert eng.status("a").display == "stale"  # a seed, once written, is an input of its step
    await eng.run()
    assert w.file("out/w.json").read_text() == "mine"
    assert eng.status("a").display == "done"
    eng.reset("a")
    assert w.file("out/w.json").exists()


async def test_stop_puts_outputs_back(tmp_path):
    w = chain(tmp_path)
    eng = w.open()
    await eng.run()
    gate = asyncio.Event()

    async def slow(ctx):
        ctx.outputs["a"].write_text("half")
        gate.set()
        await asyncio.sleep(10)

    w.code["a"] = Fake(slow)
    eng.request_change("a", "again")
    task = asyncio.ensure_future(eng.run())
    await gate.wait()
    eng.stop()
    res = await task
    assert outcome(res) == {"s": ("cancelled", "a: stopped")}
    assert w.file("out/a.txt").read_text() == "v1"
    assert eng.status("a").display == "stale"  # back to its state before it started, request still pending


async def test_parallel_stages(tmp_path):
    stages = {"s": ["a"], "t": ["b"]}
    steps = {"a": "outputs:\n  - {artifact: a, path: out/a.txt}\n", "b": "outputs:\n  - {artifact: b, path: out/b.txt}\n"}
    for limit, expect in ((1, False), (2, True)):
        w = World(tmp_path / str(limit), stages, steps, config=f"pipeline: {{max_parallel_stage: {limit}}}\n")
        live = {"now": 0, "max": 0}

        def slow(name, live=live):
            async def run(ctx):
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
                await asyncio.sleep(0.05)
                await writer(name)(ctx)
                live["now"] -= 1
            return run

        w.code = {"a": Fake(slow("a")), "b": Fake(slow("b"))}
        await w.open().run()
        assert (live["max"] == 2) is expect


async def test_cost_limit(tmp_path):
    w = chain(tmp_path, config="pipeline: {max_cost: 1.0}\n")

    async def spend(ctx):
        ctx._add_cost(1.5)
        await writer("a")(ctx)

    w.code["a"] = Fake(spend)
    eng = w.open()
    res = await eng.run()
    assert outcome(res) == {"s": ("blocked", "cost limit reached")}
    assert w.ops.cost()["total_usd"] == 1.5
    w.ops.reset_cost()
    assert w.ops.cost()["total_usd"] == 0 and w.ops.cost()["resets"][0]["total_usd"] == 1.5


async def test_definition_change(tmp_path):
    w = chain(tmp_path)
    eng = w.open()
    await eng.run()
    write(w.home / "steps/a/notes.md", "new")
    eng = w.open()
    changed = eng.check_definitions()
    assert changed == [{"step": "a", "files": ["steps/a/notes.md"], "old_version": "1.0.0", "new_version": "1.0.0"}]
    assert eng.status("a").definition_changed and eng.status("a").display == "done"  # nothing runs by itself
    w.ops.definition_answer(["a"], "later")
    assert eng.definition_changes() == []
    write(w.home / "steps/a/notes.md", "newer")
    eng = w.open()
    await w.ops.definition_answer(["a"], "rerun")
    assert w.code["a"].calls[-1].definition_changed == ["steps/a/notes.md"]


async def test_lock_between_processes(tmp_path):
    w = chain(tmp_path)
    eng = w.open()
    other = w.open()
    other.lock.acquire()
    with pytest.raises(Exception, match="only watch"):
        await eng.run()
    other.lock.release()


async def test_events_file(tmp_path):
    w = chain(tmp_path)
    await w.open().run()
    kinds = [e["kind"] for e in read_events(w.project.events_file)]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
    assert {"stage_started", "step_started", "step_finished", "stage_finished"} <= set(kinds)
    assert all(e["run_id"] for e in read_events(w.project.events_file))


def test_step_error_is_an_exception():
    assert issubclass(StepError, Exception)


async def test_interrupted_step_is_put_back_on_open(tmp_path):
    w = chain(tmp_path)
    eng = w.open()
    await eng.run()
    gate = asyncio.Event()

    async def dies(ctx):
        ctx.outputs["a"].write_text("half")
        gate.set()
        await asyncio.sleep(10)

    w.code["a"] = Fake(dies)
    eng.request_change("a", "again")
    task = asyncio.ensure_future(eng.run())
    await gate.wait()
    eng.lock.release()  # the process dies: nothing is put back, the lock is gone
    task.cancel()
    eng2 = w.open()
    assert w.file("out/a.txt").read_text() == "v1"
    assert eng2.status("a").display == "stale"
    assert any("interrupted" in e["message"] for e in w.kinds("warning"))


Q3CORE = Path(__file__).resolve().parents[2] / "VLSIT_Q3CORE_ASIC_AI_FLOW"


@pytest.mark.skipif(not (Q3CORE / "flows/vlsit/FLOW.md").is_file(), reason="Q3CORE is not next to this repo")
def test_vlsit_statuses_in_a_new_project(tmp_path):
    project = Project.open(tmp_path / "proj")
    cfg = ConfigLayers(None, project.config_file)
    lookup = Lookup(project.q3, Q3CORE)
    flow = load_flow("vlsit", lookup, cfg)
    eng = Engine(project, flow, cfg, lookup)
    statuses = {s: eng.status(s) for s in flow.order()}
    assert statuses["spec"].display == "pending"  # its inputs are optional; a step of the flow writes the rest
    assert {s.display for s in statuses.values()} <= {"pending", "missing_input"}
    lacking = [s for s in statuses.values() if s.display == "missing_input"]
    assert lacking and all("tool role" in s.reason or "package" in s.reason for s in lacking)
