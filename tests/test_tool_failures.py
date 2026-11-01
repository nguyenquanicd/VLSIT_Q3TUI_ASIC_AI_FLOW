"""A step whose tool failed (docs/spec/tui.md "When a step fails"): the engine records the kind of failure and the flow, the TUI says every new
failure and gives a tool failure to the assistant — the first time to judge, fix what its tools can and rerun once, the second time only to
explain and ask, a third time only the notice — and the assistant can change a tool role in config/tools.json."""

import json

import pytest

from q3tui.core.ops import Ops
from q3tui.core.project import Project
from q3tui.eda.tools import ToolBroken
from q3tui.pipeline.base import StepContext, StepDef, StepFailed
from q3tui.pipeline.engine import Engine, EngineError
from q3tui.tui import failures
from tests.fakes import FakeLLM


class ToolStep(StepDef):
    """Its tool fails (ToolBroken, naming a log) until `fixed` exists; `design` makes it fail as a design problem instead."""

    title = "Tool step"

    def outputs(self, engine):
        p = engine.project.root / "out.txt"
        return [p] if p.is_file() else []

    async def run(self, ctx: StepContext) -> None:
        root = ctx.project.root
        if (root / "design").exists():
            raise StepFailed("the design does not compile")
        if not (root / "fixed").exists():
            log = root / "tool.log"
            log.write_text("[Info] RDC_CROSSING_GEN_STARTED: Started analyzing.\nPeak Memory(MB):46801\n[Error] the VC Static Server exited.\n")
            raise ToolBroken(f"the `sim` tool exited with rc=3 and no error it could read — a problem of its command / environment.\nLog: {log}")
        (root / "out.txt").write_text("ok\n")


@pytest.fixture(autouse=True)
def _kind():
    from q3tui.steps import KINDS, register_kind

    register_kind("t_tool", "tests.test_tool_failures:ToolStep")
    yield
    KINDS.pop("t_tool", None)


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "flows").mkdir()
    (tmp_path / "flows" / "tf.yaml").write_text("name: tf\nsteps:\n  - {id: sim, kind: t_tool}\n")
    (tmp_path / "q3tui.yaml").write_text("pipeline: {flow: tf}\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "tools.json").write_text(json.dumps({"roles": {"sim": {"cmd": "vcs {files}", "timeout_s": 60, "env": {"A": "1"}}}}))
    return Project.open(tmp_path)


async def test_the_engine_records_what_kind_of_failure_it_was(proj):
    eng = Engine(proj)
    assert await eng.run(yes=True) != "complete"
    f = eng.state.steps["sim"].failure
    assert f["kind"] == "tool" and f["flow"] == "tf" and f["at"]
    (proj.root / "design").write_text("")
    await eng.run(yes=True)
    assert eng.state.steps["sim"].failure["kind"] == "step"
    (proj.root / "design").unlink()
    (proj.root / "fixed").write_text("")
    assert await eng.run(yes=True) == "complete" and eng.state.steps["sim"].failure is None


async def test_the_failures_are_read_handled_once_and_forgotten_when_fixed(proj):
    eng = Engine(proj)
    await eng.run(yes=True)
    [f] = failures.failed(proj)
    assert f.step == "sim" and f.kind == "tool" and failures.recent(f)
    assert failures.note(proj, f) == 1 and failures.note(proj, f) == 0  # (this occurrence: handled once, whichever TUI)
    assert failures.take_rerun(proj, f) and not failures.take_rerun(proj, f)  # (one rerun)
    text = failures.prompt(proj, f, 1)
    assert text.startswith("[Tool failure] Step `sim` of the tf flow") and "rerun_failed_step(step='sim')" in text
    assert "Peak Memory(MB):46801" in text and '"timeout_s": 60' in text and "This machine:" in text  # (the log tail, the role, the memory)
    assert failures.prompt(proj, f, 2).startswith("[Tool failure, again]") and "rerun_failed_step" not in failures.prompt(proj, f, 2)
    await eng.run(yes=True)  # (the same failure again: a new occurrence, the same signature)
    [g] = failures.failed(proj)
    assert g.at != f.at or g.sig == f.sig
    (proj.root / "fixed").write_text("")
    await eng.run(yes=True)
    failures.forget_fixed(proj)
    assert failures.failed(proj) == [] and failures.load(proj) == {}


def test_a_tool_role_is_changed_in_config_tools_json(proj):
    ops = Ops(Engine(proj))
    ops.set_tool_role("sim", "timeout_s", 7200)
    ops.set_tool_role("sim", "env", {"B": "2", "A": None})
    ops.set_tool_role("sim", "modules", "synopsys/vcs synopsys/verdi")
    role = json.loads((proj.config_dir / "tools.json").read_text())["roles"]["sim"]
    assert role == {"cmd": "vcs {files}", "timeout_s": 7200, "env": {"B": "2"}, "modules": ["synopsys/vcs", "synopsys/verdi"]}
    assert list((proj.state_dir / "bkp").rglob("tools.json"))  # (backed up first)
    with pytest.raises(EngineError, match="unknown tool field"):
        ops.set_tool_role("sim", "parse", "vcs")
    with pytest.raises(EngineError, match="no tool role 'lint'"):
        ops.set_tool_role("lint", "timeout_s", 5)


async def test_the_tui_says_it_and_the_assistant_judges_fixes_once_then_asks(proj, monkeypatch):
    from q3tui.llm import runtime
    from q3tui.tui.app import Q3TUIApp

    llm = FakeLLM()
    monkeypatch.setattr(runtime, "run_stage", llm)
    app = Q3TUIApp(proj)
    said = []
    app.notify = lambda msg, **kw: said.append((kw.get("title"), msg))

    async def settle(pilot):
        await app.workers.wait_for_complete()
        app._failures_mtime = 0.0  # (a scan now, not at the next tick)
        app._check_failures()
        app._tick()
        await pilot.pause()
        await app.workers.wait_for_complete()

    async with app.run_test(size=(150, 45)) as pilot:
        app.start_run()
        await settle(pilot)
        assert ("✖ sim failed", "tf · sim: the `sim` tool exited with rc=3 and no error it could read — a problem of its command / environment.") in said
        assert app._failed_now == ["sim"]
        asked = [c for c in llm.calls if c.name == "assistant"]
        assert len(asked) == 1 and "[Tool failure] Step `sim` of the tf flow" in asked[0].prompt and "Peak Memory(MB):46801" in asked[0].prompt
        chat = "\n".join(line.text for line in app.query_one("#activity").lines)
        assert "Q3TUI" in chat and "sim: the tool failed" in chat
        # the assistant's one rerun (its fix did not help): the same failure again → it explains and asks, no rerun
        assert app.rerun_failed("other").startswith("no tool failure of 'other'")
        assert app.rerun_failed("sim").startswith("run started")
        await settle(pilot)
        asked = [c for c in llm.calls if c.name == "assistant"]
        assert len(asked) == 2 and "\n\n[Tool failure, again] Step `sim`" in asked[1].prompt
        assert app.rerun_failed("sim").startswith("not rerun")
        # a third time (you ran it again yourself): only the notice
        app.start_run()
        await settle(pilot)
        assert len([c for c in llm.calls if c.name == "assistant"]) == 2 and len([s for s in said if s[0] == "✖ sim failed"]) == 3
        # fixed: the mark goes, and the next failure is a new one
        (proj.root / "fixed").write_text("")
        app.start_run()
        await settle(pilot)
        assert app._failed_now == [] and failures.load(proj) == {}
