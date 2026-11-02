"""The full unattended run (core/chain.py, `q3tui auto`): the flows in order; a flow that changed the RTL makes the flows that check it run again."""

from __future__ import annotations

import anyio
import pytest

from q3tui.core import chain
from q3tui.core.events import EventBus
from q3tui.core.project import Project


@pytest.fixture
def project(tmp_path):
    (tmp_path / "q3tui.yaml").write_text("pipeline: {flow: spec}\n")
    p = Project.open(tmp_path)
    p.rtl_dir.mkdir(parents=True, exist_ok=True)
    (p.rtl_dir / "top.sv").write_text("module top; endmodule\n")
    return p


def fake_flows(monkeypatch, project, script: dict[str, list]):
    """script: flow -> what each of its runs does, in order: True (passes), "fix" (passes after changing the RTL), or a failure text."""
    ran: list[str] = []
    count: dict[str, int] = {}

    async def run_flow(proj, bus, name):
        n = count.get(name, 0)
        count[name] = n + 1
        ran.append(name)
        todo = script.get(name, [True])
        what = todo[min(n, len(todo) - 1)]
        if what == "fix":
            f = proj.rtl_dir / "top.sv"
            f.write_text(f.read_text() + f"// {name} fix {n}\n")
            return True, "complete"
        if what is True:
            return True, "complete"
        return False, what

    monkeypatch.setattr(chain, "run_flow", run_flow)
    return ran


def go(project, **kw):
    return anyio.run(lambda: chain.run_chain(project, EventBus(), **kw))


def test_every_flow_once_when_nothing_changes_the_rtl(monkeypatch, project):
    ran = fake_flows(monkeypatch, project, {})
    result = go(project)
    assert ran == ["spec", "rtl", "dv", "sanity", "fpga"] and result.ok
    assert project.cfg.pipeline.auto_answer  # (unattended)


def test_a_sanity_fix_runs_dv_again_and_an_fpga_fix_dv_and_sanity(monkeypatch, project):
    ran = fake_flows(monkeypatch, project, {"sanity": ["fix", True], "fpga": ["fix", True]})
    result = go(project)
    assert ran == ["spec", "rtl", "dv", "sanity", "dv", "fpga", "dv", "sanity"]  # (spec / rtl never again: the fixes went through rtl)
    assert result.ok and [s.changed for s in result.stages] == [False, False, False, True, False, True, False, False]


def test_a_flow_that_does_not_pass_stops_it(monkeypatch, project):
    ran = fake_flows(monkeypatch, project, {"sanity": ["fix loop stopped: no improvement (3 open)"]})
    result = go(project)
    assert ran == ["spec", "rtl", "dv", "sanity"] and not result.ok and result.stopped.startswith("sanity did not pass")


def test_bounded_when_the_flows_keep_changing_the_rtl(monkeypatch, project):
    ran = fake_flows(monkeypatch, project, {"sanity": ["fix"], "fpga": ["fix"]})
    result = go(project, max_runs=2)
    assert ran == ["spec", "rtl", "dv", "sanity", "dv", "fpga"]  # (fpga's fix would need dv a third time)
    assert not result.ok and result.stopped.startswith("dv ran 2 times")


def test_an_unknown_flow_is_said_before_anything_runs(monkeypatch, project):
    ran = fake_flows(monkeypatch, project, {})
    with pytest.raises(Exception, match="nope"):
        go(project, chain=["spec", "nope"])
    assert ran == []


# -- a tool failure: once more, then the tool fix, then once more --------------------------------------------------------------------------------------

def tool_flows(monkeypatch, project, script: dict[str, list], fix=None):
    """Like fake_flows, with "tool:<error>": the flow fails on a tool failure (recorded as the engine records one); `fix`: what the tool fix answers."""
    from datetime import datetime

    from q3tui.tui.failures import Failure

    ran, count, recorded, fixes = [], {}, [], []

    async def run_flow(proj, bus, name):
        n = count.get(name, 0)
        count[name] = n + 1
        ran.append(name)
        todo = script.get(name, [True])
        what = todo[min(n, len(todo) - 1)]
        if what is True:
            return True, "complete"
        if isinstance(what, str) and what.startswith("tool:"):
            recorded.append(Failure("rdc_check", name, "tool", datetime.now().isoformat(timespec="milliseconds"), what[5:]))
            return False, "ended 'failed'"
        return False, what

    async def fix_tool(proj, bus, name, failure, tried=None):
        fixes.append((name, failure.error))
        return fix

    monkeypatch.setattr(chain, "run_flow", run_flow)
    monkeypatch.setattr(chain, "tool_failure", lambda proj, since: next((f for f in reversed(recorded) if f.at >= since), None))
    monkeypatch.setattr(chain, "fix_tool", fix_tool)
    return ran, fixes


def test_a_tool_failure_goes_to_the_tool_fix_at_once_and_the_flow_runs_again(monkeypatch, project):
    ran, fixes = tool_flows(monkeypatch, project, {"sanity": ["tool:the `rdc` tool exited with rc=139", True]},
                            fix=chain.ToolFix(summary="black-boxed the memories", rerun=True))
    result = go(project)
    assert result.ok and ran == ["spec", "rtl", "dv", "sanity", "sanity", "fpga"] and fixes == [("sanity", "the `rdc` tool exited with rc=139")]
    assert "after the tool fix: black-boxed the memories" in result.stages[3].note


def test_at_most_two_tool_fixes_per_flow_run(monkeypatch, project):
    ran, fixes = tool_flows(monkeypatch, project, {"sanity": ["tool:the `rdc` tool exited with rc=139"] * 5},
                            fix=chain.ToolFix(summary="raised the timeout", rerun=True))
    result = go(project)
    assert not result.ok and ran.count("sanity") == 3 and len(fixes) == 2 and "still failed after 2 tool fix(es)" in result.stopped and "fpga" not in ran


def test_a_tool_fix_that_needs_the_user_stops_the_chain(monkeypatch, project):
    ran, fixes = tool_flows(monkeypatch, project, {"sanity": ["tool:the `rdc` tool exited with rc=139"] * 3},
                            fix=chain.ToolFix(summary="out of memory", rerun=False, user_action="free memory or use a bigger machine"))
    result = go(project)
    assert not result.ok and ran.count("sanity") == 1 and "free memory or use a bigger machine" in result.stopped and "fpga" not in ran


def test_a_design_failure_is_not_run_again(monkeypatch, project):
    ran, fixes = tool_flows(monkeypatch, project, {"dv": ["ended 'failed'"]})
    result = go(project)
    assert not result.ok and ran.count("dv") == 1 and not fixes


def test_the_tool_fix_stage_may_change_the_tools_role_but_never_its_command(monkeypatch, project):
    import json

    from q3tui.llm import runtime
    from q3tui.llm.runtime import StageResult
    from q3tui.tui.failures import Failure

    project.config_dir.mkdir(parents=True, exist_ok=True)
    (project.config_dir / "tools.json").write_text(json.dumps({"roles": {"rdc": {"cmd": "vc_static_shell -f {script}", "timeout_s": 3600}}}))
    seen = {}

    async def fake(stage, cfg, emit):
        tools = {t.name: t for t in stage.sdk_tools}
        seen["prompt"], seen["tools"], seen["deny"] = stage.prompt, sorted(tools), stage.deny_dirs
        seen["bad_opt"] = (await tools["set_step_option"].handler({"step": "rdc", "key": "cmd", "value": "x"}))["content"][0]["text"]
        seen["bb"] = (await tools["set_step_option"].handler({"step": "rdc", "key": "blackbox", "value": '["m_dmem", "m_imem"]'}))["content"][0]["text"]
        seen["cmd"] = (await tools["set_tool_role"].handler({"role": "rdc", "key": "cmd", "value": "rm -rf /"}))["content"][0]["text"]
        seen["timeout"] = (await tools["set_tool_role"].handler({"role": "rdc", "key": "timeout_s", "value": "7200"}))["content"][0]["text"]
        return StageResult("", chain.ToolFix(summary="raised the timeout", rerun=True), 0.01, 3, "s")

    monkeypatch.setattr(runtime, "run_stage", fake)
    f = Failure("rdc_check", "sanity", "tool", "2026-11-02T09:46:00.000", "the `rdc` tool exited with rc=139 and no error it could read")
    out = anyio.run(lambda: chain.fix_tool(project, EventBus(), "sanity", f))
    assert out.rerun and seen["tools"] == ["get_settings", "set_settings", "set_step_option", "set_tool_role"]
    assert seen["deny"] == [project.state_dir]  # (it may read the RTL: which modules are big memories)
    assert "rdc.blackbox = null" in seen["prompt"] and "not an option offered" in seen["bad_opt"] and "rdc_check.blackbox" not in seen["prompt"]
    assert project.cfg.pipeline.step_options["rdc"]["blackbox"] == ["m_dmem", "m_imem"] and "m_dmem" in (project.root / "q3tui.yaml").read_text()
    assert "rc=139" in seen["prompt"] and "Tool role `rdc`" in seen["prompt"] and "This machine:" in seen["prompt"]
    assert "a new command is the user's" in seen["cmd"]
    roles = json.loads((project.config_dir / "tools.json").read_text())["roles"]
    assert roles["rdc"] == {"cmd": "vc_static_shell -f {script}", "timeout_s": 7200}


def test_the_tool_fix_is_told_the_memory_the_same_tool_needed_before(project):
    import json

    from q3tui.tui import failures
    from q3tui.tui.failures import Failure

    project.config_dir.mkdir(parents=True, exist_ok=True)
    (project.config_dir / "tools.json").write_text(json.dumps({"roles": {"rdc": {"cmd": "vc_static_shell -f {script}"}}}))
    log = project.state_dir / "sanity" / "rdc" / "rdc.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("$ vc_static_shell -f x.tcl\nPeak Memory(MB)     :380\nPeak Memory(MB):48846\n")
    f = Failure("rdc_check", "sanity", "tool", "2026-11-02T09:46:00.000", "the `rdc` tool exited with rc=139")
    text = failures.facts(project, f)
    assert "Memory the same tool reported" in text and ".q3tui/sanity/rdc/rdc.log" in text and "peak 47.7 GB" in text


def _fake_engine(monkeypatch, statuses: list[list[str]]):
    """Engine stand-in for run_flow: each run completes; status() after the n-th run gives statuses[n] (one status per step)."""
    from types import SimpleNamespace

    from q3tui.pipeline import engine as engine_mod

    runs = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def run(self, **k):
            runs.append(k)
            return "complete"

        def status(self):
            now = statuses[min(len(runs), len(statuses)) - 1]
            return [SimpleNamespace(name=f"s{i}", status=s) for i, s in enumerate(now)]

    monkeypatch.setattr(engine_mod, "Engine", Fake)
    monkeypatch.setattr(chain.flows, "load_flow", lambda *a, **k: None)
    return runs


def test_a_flow_left_with_only_stale_steps_runs_once_more(monkeypatch, project):
    runs = _fake_engine(monkeypatch, [["done", "stale", "stale"], ["done", "done", "done"]])
    ok, note = anyio.run(lambda: chain.run_flow(project, EventBus(), "fpga"))
    assert ok and len(runs) == 2 and "run again" in note


def test_still_stale_after_the_rerun_or_a_failed_step_does_not_pass(monkeypatch, project):
    runs = _fake_engine(monkeypatch, [["done", "stale"]])
    ok, note = anyio.run(lambda: chain.run_flow(project, EventBus(), "fpga"))
    assert not ok and len(runs) == 1 + chain.STALE_RERUNS and "not done: s1" in note
    runs = _fake_engine(monkeypatch, [["stale", "failed"]])
    ok, note = anyio.run(lambda: chain.run_flow(project, EventBus(), "fpga"))
    assert not ok and len(runs) == 1  # (not only stale: no rerun)
