"""Q3TUI's own record of a project (core/history.py, docs/spec/history.md): a version when a step finishes and when a flow passes (passed/<flow>),
in .q3tui/history/, apart from your own git; the dv triage is told what changed since a failing test passed, and the rtl change request carries
the module's diff since then."""

from __future__ import annotations

import json
import shutil
import subprocess

import anyio
import pytest
from click.testing import CliRunner

from q3tui import flows
from q3tui.core import history
from q3tui.core.cli import main
from q3tui.core.ops import Ops
from q3tui.core.project import Project
from q3tui.pipeline.base import StepFailed
from q3tui.pipeline.engine import Engine
from tests.test_dv_plain import llm, make_engine, run_all, run_step, tools_dir  # noqa: F401 - fixtures
from tests.test_parallel_runs import _kinds, _project, _write_flow, other_run  # noqa: F401 - fixtures

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _titles(project) -> list[str]:
    return [v.title for v in history.versions(project)]


def _run(project, flow: str) -> str:
    return anyio.run(lambda: Engine(project, flow=flows.load_flow(flow, project.root)).run(yes=True))


def test_a_version_when_a_step_finishes_and_when_the_flow_passes(tmp_path):
    project = _project(tmp_path)  # (the design flow ran: spec, rtl)
    assert _titles(project) == ["design passed", "design · rtl: done", "design · spec: done"]
    (v_pass, v_rtl, _) = history.versions(project, files=True)
    assert v_pass.marks == ["passed/design"] and v_rtl.files == ["src/rtl/top.sv"] and "flow: design" in v_rtl.body and "run: run_" in v_rtl.body
    assert _run(project, "design") == "complete"  # nothing to do, nothing changed: no new version
    assert len(_titles(project)) == 3
    Engine(project, flow=flows.load_flow("design", project.root)).request_change("spec", "wider")  # (the spec changes; rtl runs again, its file stays)
    assert _run(project, "design") == "complete"
    assert _titles(project) == ["design passed", "design · spec: done", "design passed", "design · rtl: done", "design · spec: done"]
    assert history.versions(project)[0].marks == ["passed/design"] and history.versions(project)[2].marks == []  # (the mark moved on)


def test_a_flow_the_fix_loop_runs_passes_too_and_a_run_of_some_steps_is_no_pass(tmp_path):
    project = _project(tmp_path)
    assert _run(project, "lb") == "complete"  # (check_b hands the fix B to the design flow, which runs within the run)
    found = history.versions(project)
    marks = {m: v.title for v in found for m in v.marks}
    assert marks["passed/lb"] == "lb passed" and marks["passed/design"] == "design passed" and found[0].title == "lb passed"
    assert any(v.title == "design · rtl: done" and "// fix: B" in history.show(project, v.rev, "src/rtl/top.sv") for v in found)
    eng = Engine(project, flow=flows.load_flow("design", project.root))
    eng.request_change("spec", "another block")
    n = len(found)
    assert anyio.run(lambda: eng.run(only="spec", yes=True)) == "complete"  # (rtl is stale now: the flow did not pass)
    assert _titles(project)[0] == "design · spec: done" and len(_titles(project)) == n + 1


def test_the_history_leaves_out_build_and_state_and_never_touches_your_own_git(tmp_path):
    project = _project(tmp_path)
    root = project.root
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "build").mkdir()
    (root / "build" / "x.log").write_text("tool output\n")
    (root / ".gitignore").write_text("*.tmp\n")
    (root / "notes.tmp").write_text("scratch\n")
    (root / "src" / "rtl" / "top.sv").write_text("module top; wire w; endmodule\n")
    rev = history.record(project, "by hand")
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", rev], cwd=root, env=history._env(project), capture_output=True, text=True).stdout.split()
    assert "src/rtl/top.sv" in files and "spec/spec.md" in files and ".gitignore" in files
    assert not [f for f in files if f.startswith(("build/", ".q3tui/")) or f.endswith(".tmp")]
    mine = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
    assert mine and all(line.startswith("??") for line in mine.splitlines())  # (your git: nothing staged, nothing committed)
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=root, capture_output=True).returncode != 0


def test_no_history_when_it_is_off(tmp_path):
    root = tmp_path / "p"
    (root / "spec").mkdir(parents=True)
    (root / "spec" / "intent.md").write_text("a block\n")
    _write_flow(root, "design", "- {id: spec, kind: t_spec}")
    (root / "q3tui.yaml").write_text("pipeline: {flow: design, history: false}\n")
    project = Project.open(root)
    assert _run(project, "design") == "complete"
    assert not history.folder(project).exists() and "the history is off" in Ops(Engine(project)).history_text()


def test_restore_puts_files_back_as_they_were_and_records_it(tmp_path):
    project = _project(tmp_path)
    root = project.root
    first = history.versions(project)[0].rev
    (root / "src" / "rtl" / "top.sv").write_text("module top; wire broken; endmodule\n")
    (root / "src" / "rtl" / "extra.sv").write_text("module extra; endmodule\n")
    history.record(project, "fpga · rtl: done")
    ops = Ops(Engine(project))
    assert "+module top; wire broken; endmodule" in ops.history_diff(first, path="src/rtl")
    said = ops.restore_version(first[:8], ["src/rtl"])
    assert "1 file(s) written, 1 deleted (src/rtl/extra.sv)" in said
    assert (root / "src" / "rtl" / "top.sv").read_text() == "module top;\nendmodule\n" and not (root / "src" / "rtl" / "extra.sv").exists()
    assert _titles(project)[0] == f"restored src/rtl from {first[:8]}" and list((project.state_dir / "bkp").glob("*/src/rtl/extra.sv"))


def test_restore_waits_for_a_run_of_another_flow(tmp_path, other_run):
    project = _project(tmp_path)
    other_run(project, "dv")
    from q3tui.pipeline.engine import EngineError

    with pytest.raises(EngineError, match="a run of dv is going on"):
        Ops(Engine(project)).restore_version("HEAD", ["src/rtl"])


def test_the_history_commands(tmp_path):
    project = _project(tmp_path)
    r = CliRunner().invoke(main, ["-C", str(project.root), "history"])
    assert r.exit_code == 0 and "design passed [passed/design]" in r.output and "design · rtl: done — src/rtl/top.sv" in r.output
    r = CliRunner().invoke(main, ["-C", str(project.root), "history", "show", "passed/design", "src/rtl/top.sv"])
    assert r.exit_code == 0 and r.output == "module top;\nendmodule\n"
    r = CliRunner().invoke(main, ["-C", str(project.root), "history", "diff", "HEAD~1", "--own"])
    assert r.exit_code == 0 and "+module top;" in r.output


# -- the dv triage: a test that passed before ------------------------------------------------------------------------------------------------

def test_a_test_that_passed_before_is_triaged_with_what_changed_since_and_the_rtl_request_carries_the_diff(tmp_path, tools_dir, llm):
    eng = make_engine(tmp_path, tools_dir)
    run_all(eng)
    run_step(eng, "simulate")  # (both tests pass)
    results = json.loads((tmp_path / "schemas" / "dv_test_results.json").read_text())
    passed = {t["tc_id"]: t["passed"] for t in results["tests"]}
    project = eng.project
    assert passed["TC-002"]["rev"] and passed["TC-002"]["rev"] in [v.rev for v in history.versions(project)]
    # another flow changes the RTL (an FPGA timing fix), then TC-002 fails
    leaf = tmp_path / "src" / "rtl" / "leaf_b.sv"
    leaf.write_text(leaf.read_text().replace("endmodule", "  // retimed for the FPGA\nendmodule"))
    history.record(project, "fpga · rtl: done", "flow: fpga\nstep: rtl")
    (tmp_path / "q3tui.yaml").write_text((tmp_path / "q3tui.yaml").read_text().replace(" pass {project}", " failtc2 {project}"))
    llm.vlsit_triage_verdicts = [{"id": "TC-002", "verdict": "rtl_bug", "module": "leaf_b", "summary": "b is late", "request": "register b"}]
    eng = Engine(Project.open(tmp_path))
    with pytest.raises(StepFailed, match="handed to the rtl flow"):
        run_step(eng, "simulate")
    (stage,) = [c for c in llm.calls if c.name == "dv_triage"]
    assert f"### TC-002: passed with version {passed['TC-002']['rev'][:8]}" in stage.prompt
    assert "fpga · rtl: done: leaf_b.sv" in stage.prompt and "+  // retimed for the FPGA" in stage.prompt
    rtl = Engine(Project.open(tmp_path), flow=flows.load_flow("rtl"))
    (req,) = rtl.state.feedback["rtl"]
    assert req.startswith("[rtl:leaf_b] From the simulation of the testbench (TC-002): b is late register b")
    assert "TC-002 passed with an earlier version of this module" in req and "fpga · rtl: done" in req and "+  // retimed for the FPGA" in req
    # still failing: it keeps the version it last passed with
    results = json.loads((tmp_path / "schemas" / "dv_test_results.json").read_text())
    assert {t["tc_id"]: t["passed"] for t in results["tests"]}["TC-002"] == passed["TC-002"]


def test_a_test_that_never_passed_gets_no_since_section(tmp_path, tools_dir, llm):
    llm.vlsit_triage_verdicts = [{"id": "TC-002", "verdict": "tb_bug", "summary": "x", "request": "y"}]
    eng = make_engine(tmp_path, tools_dir, run_mode="failtc2")
    run_all(eng)
    run_step(eng, "simulate")
    (stage,) = [c for c in llm.calls if c.name == "dv_triage"]
    assert "## Tests that passed before" not in stage.prompt


def test_the_history_screen(tmp_path):
    from q3tui.tui.app import Q3TUIApp
    from q3tui.tui.screens import HistoryScreen

    project = _project(tmp_path)
    app = Q3TUIApp(project)

    async def main():
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.press("H")
            await pilot.pause()
            assert isinstance(app.screen, HistoryScreen) and [v.title for v in app.screen.versions] == _titles(project)
            await pilot.press("down")  # (design · rtl: done: what it changed)
            await pilot.pause()
            shown = str(app.screen.query_one("#hist-text").content.renderables[0])
            assert "design · rtl: done" in shown and "src/rtl/top.sv" in shown
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HistoryScreen)

    anyio.run(main)
