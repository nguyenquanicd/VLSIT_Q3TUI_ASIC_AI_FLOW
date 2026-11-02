"""The dv triage's debug runs (flows/dv/debug.py, eda/vcd.py): a failing test runs again with a waveform dump (the tool role `wave`), the triage reads it, and a fix is
handed over only with evidence from such a run. Fake tools (a script that writes a VCD), fake LLM; no simulator."""

import asyncio
import sys
import threading
from pathlib import Path

import pytest

from q3tui import flows
from q3tui.core.project import Project
from q3tui.eda import vcd
from q3tui.flows.dv import debug
from q3tui.pipeline.base import StepFailed
from q3tui.pipeline.engine import Engine
from tests.test_dv_plain import llm, make_engine, run_all, run_step, tools_dir  # noqa: F401 - the fixtures

VCD = """$date today $end
$timescale 1ps $end
$scope module tb_top $end
$scope module u_dut $end
$var wire 1 ! o_flag $end
$var wire 8 " o_data [7:0] $end
$upscope $end
$var reg 1 # clk $end
$upscope $end
$enddefinitions $end
#0
$dumpvars
0!
b0 "
0#
$end
#5000
1#
b101 "
#10000
0#
1!
#15000
1#
bx "
"""

WAVE = '''import sys
tc, out, scopes = sys.argv[1], sys.argv[2], sys.argv[3:]
if not all(s.startswith("tb_top") for s in scopes):
    print("Error-[UCLI-DUMP-OBJ-NOT-FOUND] Object(s) not found"); sys.exit(1)
open(out, "w").write(open(sys.argv[0].replace("wave.py", "wave.vcd")).read())
print(f"TC_DETAIL {tc} FAIL: the checked value was wrong"); print(f"TC_RESULT {tc} FAIL")
'''


def test_the_vcd_reader_lists_signals_gives_values_in_a_window_and_finds_a_value(tmp_path):
    p = tmp_path / "a.vcd"
    p.write_text(VCD)
    h = vcd.header(p)
    assert [v.name for v in h.vars] == ["tb_top.u_dut.o_flag", "tb_top.u_dut.o_data", "tb_top.clk"] and h.ns_per_tick == 0.001 and h.end_ns() == 15.0
    assert [v.name for v in vcd.find_vars(h, "u_dut")] == ["tb_top.u_dut.o_flag", "tb_top.u_dut.o_data"]
    text = vcd.values(p, ["u_dut.o_data", "o_flag", "nope"], 0, 12)
    assert "nope: not in this dump" in text
    assert "tb_top.u_dut.o_data [8]: 'h00 at 0 ns; then 5: 'h05" in text and "tb_top.u_dut.o_flag [1]: 0 at 0 ns; then 10: 1" in text
    assert "15:" not in text  # (outside the window)
    assert vcd.find(p, "o_data", "0x5") == "tb_top.u_dut.o_data = 'h05 at 5 ns"
    assert vcd.find(p, "tb_top.clk", "1", nth=2) .startswith("tb_top.clk = 1 at 15 ns")
    assert "never becomes 1" in vcd.find(p, "o_flag", "1", after_ns=11)


def test_a_role_script_gets_its_placeholders_and_keeps_tcl_braces():
    text = debug.fill("dump -file {dump}\ndump -add {{scopes}} -depth {depth}\nrun {until}\nproc p {} { set a {x} }\n",
                      {"dump": Path("/w/D1.dump"), "scopes": ["tb_top.a", "tb_top.b"], "depth": 1, "until": ""})
    assert text == "dump -file /w/D1.dump\ndump -add {tb_top.a tb_top.b} -depth 1\nrun \nproc p {} { set a {x} }\n"


def with_wave(tmp_path, tools_dir):
    (tools_dir / "wave.py").write_text(WAVE)
    (tools_dir / "wave.vcd").write_text(VCD)
    y = tmp_path / "q3tui.yaml"
    y.write_text(y.read_text().replace("  roles:\n", f"  roles:\n    wave: {{cmd: '{sys.executable} {tools_dir}/wave.py {{tc}} {{vcd}} {{scopes}}', parse: vcs}}\n", 1))
    return Engine(Project.open(tmp_path))


def call_tool(stage, name, args):
    """What the LLM does with an in-process tool (run in a thread of its own: the fake stage is called from the engine's event loop)."""
    (t,) = [t for t in stage.sdk_tools if t.name == name]
    out = {}
    th = threading.Thread(target=lambda: out.update(asyncio.run(t.handler(args))))
    th.start()
    th.join()
    return out["content"][0]["text"]


def test_the_triage_probes_a_test_and_an_rtl_fix_goes_over_with_its_evidence(tmp_path, tools_dir, llm):
    seen = {}

    def triage(stage):
        seen["prompt"] = stage.prompt
        seen["tools"] = [t.name for t in stage.sdk_tools]
        assert "not found" in call_tool(stage, "sim_probe", {"test": "TC-002", "scopes": ["u_dut"]}).lower()  # (a wrong path: the tool's message, no dump)
        seen["probe"] = call_tool(stage, "sim_probe", {"test": "TC-002", "scopes": ["tb_top.u_dut"]})
        seen["values"] = call_tool(stage, "wave_values", {"dump": "D1", "signals": ["o_flag"], "end_ns": 12})
        return [{"id": "TC-002", "verdict": "rtl_bug", "module": "leaf_b", "summary": "b is not registered", "request": "register b on the clock edge",
                 "evidence": "D1: tb_top.u_dut.o_flag rises at 10 ns, one cycle late"}]

    llm.vlsit_triage_verdicts = triage
    eng = make_engine(tmp_path, tools_dir, run_mode="failtc2")
    run_all(eng)
    eng = with_wave(tmp_path, tools_dir)
    with pytest.raises(StepFailed, match="handed to the rtl flow"):
        run_step(eng, "simulate")
    assert seen["tools"] == ["sim_probe", "wave_list", "wave_values", "wave_find"] and "show it before you hand a fix over" in seen["prompt"]
    assert seen["probe"].startswith("D1: TC-002 ran with a dump of tb_top.u_dut") and "TC_RESULT TC-002 FAIL" in seen["probe"] and "tb_top.u_dut.o_flag" in seen["probe"]
    assert "then 10: 1" in seen["values"]
    assert (tmp_path / "build/sim/tb/debug/D1.vcd").is_file()
    rtl = Engine(Project.open(tmp_path), flow=flows.load_flow("rtl")).state.feedback["rtl"]
    assert rtl == ["[rtl:leaf_b] From the simulation of the testbench (TC-002): b is not registered register b on the clock edge Evidence (a debug run of the simulation "
                   "triage): D1: tb_top.u_dut.o_flag rises at 10 ns, one cycle late"]
    assert [c.name for c in llm.calls].count("dv_triage") == 1


def test_a_fix_without_evidence_is_asked_for_it_once_then_handed_over_as_nothing(tmp_path, tools_dir, llm):
    asked = []

    def triage(stage):
        asked.append(stage)
        return [{"id": "TC-002", "verdict": "rtl_bug", "module": "leaf_b", "summary": "b looks wrong", "request": "register b",
                 "evidence": "I read the whole path" if len(asked) == 1 else "D7: made up"}]

    llm.vlsit_triage_verdicts = triage
    eng = make_engine(tmp_path, tools_dir, run_mode="failtc2")
    run_all(eng)
    eng = with_wave(tmp_path, tools_dir)
    with pytest.raises(StepFailed, match="need your decision"):
        run_step(eng, "simulate")
    assert len(asked) == 2 and asked[1].resume == "s" and asked[1].prompt.startswith("# Task: show it on a run") and asked[1].sdk_tools  # (the same session, with the tools)
    assert not Engine(Project.open(tmp_path), flow=flows.load_flow("rtl")).state.feedback.get("rtl")  # nothing handed over
    (q,) = [q for q in eng.questions() if q["step"] == "simulate" and q["status"] == "open"]
    assert "no debug run showed it" in q["question"] and "register b" in q["question"]


def test_without_the_wave_role_the_triage_has_no_debug_tools_and_works_as_before(tmp_path, tools_dir, llm):
    llm.vlsit_triage_verdicts = [{"id": "TC-002", "verdict": "rtl_bug", "module": "leaf_b", "summary": "b is not registered", "request": "register b"}]
    eng = make_engine(tmp_path, tools_dir, run_mode="failtc2")
    run_all(eng)
    with pytest.raises(StepFailed, match="handed to the rtl flow"):
        run_step(eng, "simulate")
    (stage,) = [c for c in llm.calls if c.name == "dv_triage"]
    assert not stage.sdk_tools and "Debug runs" not in stage.prompt
