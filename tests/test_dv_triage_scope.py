"""Where a testbench fix goes, and how a fix that keeps coming back ends (flows/dv/triage.py, flows/dv/plain/tb.py): a tb_bug in the shared tb_top is
`[tb:top]` — a small session on tb_top.sv, the test cases rewritten only when they use what changed; an unattended run makes one wider try instead of
asking; the answers it gives with the defaults do not start the fix rounds over, yours do."""

from __future__ import annotations

import pytest

from q3tui.core.project import Project
from q3tui.flows.dv.plain import gen as tb_gen
from q3tui.flows.dv.plain.plan import TbUnitResult
from q3tui.llm.runtime import StageResult
from q3tui.pipeline.base import StepFailed
from q3tui.pipeline.engine import Engine
from tests import vlsit_fakes
from tests.test_dv_plain import TB_TOP, failing, llm, make_engine, run_all, run_step, tools_dir  # noqa: F401 - fixtures

TOP_WITH_HELPER = TB_TOP.replace("  initial begin", "  task automatic helper();\n    #1;\n  endtask\n  int mon_viol_cnt;\n  initial begin")


@pytest.fixture
def top_change():
    """The tb_top change session: `edit(text) -> text` is what it does to tb_top.sv (it goes before the module's own fake)."""
    state = {"edit": lambda t: t.replace("#1;", "#2;")}

    def handler(fake, stage, emit):
        if stage.name != "tb_top_change":
            return None
        p = stage.write_files[0]
        p.write_text(state["edit"](p.read_text()))
        return StageResult("", TbUnitResult(summary="tb_top changed"), 0.0, 1, "s")

    vlsit_fakes.HANDLERS.insert(0, handler)
    yield state
    vlsit_fakes.HANDLERS.remove(handler)


def test_the_interface_of_tb_top_and_what_a_change_touches():
    text = "module tb_top;\n  // task automatic old_one();\n  task automatic helper(input int n);\n  endtask\n  function automatic logic [7:0] f(int a);\n" \
           "  endfunction\n  logic [3:0] a, b = 0;\n  `define CHECK(x) x\nendmodule\n"
    iface = tb_gen.top_interface(text)
    assert set(iface) == {"helper", "f", "a", "b", "`CHECK"}  # (a commented-out task is not there)
    assert tb_gen.interface_changes(text, text.replace("endtask", "  #5;\n  endtask")) == set()  # a body that changed: nothing a test calls
    assert tb_gen.interface_changes(text, text.replace("helper(input int n)", "helper(input int n, input bit q)")) == {"helper"}
    assert tb_gen.interface_changes(text, text.replace("  logic [3:0] a, b = 0;\n", "")) == {"a", "b"}
    assert tb_gen.interface_changes("", text) is None  # (nothing to compare: every test case counts as affected)
    assert {"helper", "`CHECK"} <= tb_gen.identifiers("task automatic tc_001_x();\n  helper(3);\n  `CHECK(1)\nendtask\n")


def test_a_change_request_for_tb_top_is_a_small_session_and_the_test_cases_stay_unless_they_use_what_changed(tmp_path, tools_dir, llm, top_change):
    eng = make_engine(tmp_path, tools_dir)
    run_all(eng)
    top = tmp_path / "src" / "tb" / "tb_top.sv"
    top.write_text(TOP_WITH_HELPER)
    tc1 = next((tmp_path / "src" / "tb" / "tests").glob("tc_001_*.sv"))
    tc1.write_text(tc1.read_text().replace("endtask", "  helper();\nendtask"))  # (TC-001 calls tb_top's helper, TC-002 does not)
    eng.request_change("tb", "[tb:top] make the monitor reset-aware")
    eng = Engine(Project.open(tmp_path))
    n = len(llm.calls)
    run_step(eng, "tb")
    new = [c.name for c in llm.calls[n:]]
    assert new == ["tb_top_change"]  # a body-only change: no full tb_top rewrite, no test case rewritten
    stage = llm.calls[n]
    assert "make the monitor reset-aware" in stage.prompt and "task automatic helper();" in stage.prompt and stage.write_files == [top]
    assert "#2;" in top.read_text()
    # a change that touches what TC-001 uses: TC-001 is rewritten, TC-002 is not
    top_change["edit"] = lambda t: t.replace("task automatic helper();", "task automatic helper(input int n);")
    eng.request_change("tb", "[tb:top] the helper takes a count")
    eng = Engine(Project.open(tmp_path))
    n = len(llm.calls)
    run_step(eng, "tb")
    rewritten = [f.name for c in llm.calls[n:] if c.name.startswith("tb_g") for f in c.write_files]
    assert [c.name for c in llm.calls[n:]][0] == "tb_top_change" and rewritten == [tc1.name]


def test_a_testbench_bug_in_the_shared_top_goes_to_tb_top_not_to_the_test(tmp_path, tools_dir, llm):
    eng = failing(tmp_path, tools_dir, llm, [{"id": "TC-002", "verdict": "tb_bug", "module": "tb_top", "summary": "the APB monitor is not reset-aware",
                                             "request": "ignore APB tracking while the DUT is in reset"}])
    run_step(eng, "simulate")
    assert eng.state.feedback["tb"] == ["[tb:top] From the simulation triage (TC-002): the APB monitor is not reset-aware ignore APB tracking while the DUT is in reset"]
    assert eng.state.step_meta["simulate"]["history"][-1]["key"] == "tb_bug|top|TC-002"


TB_BUG = [{"id": "TC-002", "verdict": "tb_bug", "summary": "the check is wrong", "request": "check b one cycle later"}]


def test_unattended_a_fix_that_keeps_coming_back_gets_one_wider_try_then_the_rounds_end(tmp_path, tools_dir, llm):
    eng = failing(tmp_path, tools_dir, llm, TB_BUG)
    eng.project.cfg.pipeline.auto_answer = True  # (an unattended run)
    for _ in range(2):  # handed over twice, scoped to the test
        run_step(eng, "simulate")
    assert eng.state.feedback["tb"] == ["[tb:TC-002] From the simulation triage (TC-002): the check is wrong check b one cycle later"] * 2
    run_step(eng, "simulate")  # it came back twice: no question, one wider try — tb_top and the test
    wide = eng.state.feedback["tb"][2:]
    assert [f.split("]")[0] for f in wide] == ["[tb:top", "[tb:TC-002"]
    assert all("came back 2 time(s) after its fix (tried: check b one cycle later; check b one cycle later)" in f and "tb_top.sv" in f for f in wide)
    assert not eng.by_name["simulate"].question_list(eng)
    with pytest.raises(StepFailed, match="need your decision on SIM1"):  # the wider try did not do it either: now a question
        run_step(eng, "simulate")
    assert eng.state.step_meta["simulate"]["rounds"] == 4
    assert eng._auto_answer_failure(eng.by_name["simulate"])  # the unattended run answers it with the default …
    with pytest.raises(StepFailed, match="need your decision"):
        run_step(eng, "simulate")
    assert eng.state.step_meta["simulate"]["rounds"] == 5  # … which does not start the rounds over
    with pytest.raises(StepFailed, match="still failing after 5 fix round"):
        run_step(eng, "simulate")
    calls = llm.vlsit_triage_calls
    eng.answer(eng.by_name["simulate"].question_list(eng)[-1]["id"], "check b on the falling edge")  # yours does
    with pytest.raises(StepFailed, match="need your decision"):
        run_step(eng, "simulate")
    assert llm.vlsit_triage_calls == calls + 1 and eng.state.step_meta["simulate"]["rounds"] == 1


def test_attended_a_fix_that_keeps_coming_back_is_still_a_question(tmp_path, tools_dir, llm):
    eng = failing(tmp_path, tools_dir, llm, TB_BUG)
    for _ in range(2):
        run_step(eng, "simulate")
    with pytest.raises(StepFailed, match="need your decision on SIM1"):
        run_step(eng, "simulate")
    assert len(eng.state.feedback["tb"]) == 2
