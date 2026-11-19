"""The ECO flow (q3tui/flows/eco/, docs/spec/eco-flow.md): no live LLM (a fake answers by stage name), no EDA tool (Python scripts stand in for
Design Compiler, Formality and PrimeTime)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from q3tui import flows
from q3tui.core.project import Project
from q3tui.flows.eco.eco_eq1.step import lec_reuse
from q3tui.flows.eco.eco_eq2.step import own_words, route
from q3tui.flows.eco.eco_inputs.step import parse_paths
from q3tui.flows.eco.lib import tcl
from q3tui.flows.eco.lib.models import EqAdvice, NetlistEdits, RtlAlternative, RtlPlan, RtlUpdate
from q3tui.pipeline.engine import Engine

RTL = """module blk (input i_clk, input i_rst_n, input [3:0] i_a, input i_v, output reg [3:0] o_y, output o_r);
  always @(posedge i_clk or negedge i_rst_n) if (!i_rst_n) o_y <= 0; else if (i_v) o_y <= i_a;
  assign o_r = 1'b1;
endmodule
"""
NETLIST = """module blk ( i_clk, i_rst_n, i_a, i_v, o_y, o_r );
  input i_clk, i_rst_n, i_v;
  input [3:0] i_a;
  output [3:0] o_y;
  output o_r;
  DFFRNQ_X1 o_y_reg_0_ ( .D(n1), .CLK(i_clk), .RN(i_rst_n), .Q(o_y[0]) );
  MUX2_X1 U1 ( .I0(o_y[0]), .I1(i_a[0]), .S(i_v), .Z(n1) );
  TIEH_X1 U2 ( .Z(o_r) );
  TIEL_X1 spare_0 ( );
  MUX2_X4 spare_1 ( );
endmodule
"""
SPEC = "# blk\n\n## Outputs\n\no_r is always 1.\n"
# Design Compiler: writes the ECO NETLIST (the ORG netlist + the edit files it sourced and their edits, as comments); an edit naming BAD is an error
FAKE_DC = """import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
org = Path(re.search(r'read_verilog -netlist "([^"]+)"', text).group(1)).read_text()
srcs = re.findall(r'source -echo -verbose "([^"]+)"', text)
if any('BAD' in Path(s).read_text() for s in srcs):
    print("Error: Cannot find cell 'BAD'. (UID-109)")
    sys.exit(0)
out = Path(re.search(r'write -format verilog -hierarchy -output "([^"]+)"', text).group(1))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(org + ''.join('// sourced ' + Path(s).name + ': ' + ' | '.join(Path(s).read_text().splitlines()) + '\\n' for s in srcs))
print('Q3TUI_ECO_APPLY: DONE')
"""
# Formality: the verdict is fm_result.txt beside this script (default SUCCEEDED)
FAKE_FM = """import sys
from pathlib import Path
ctl = Path(__file__).parent / 'fm_result.txt'
res = ctl.read_text().strip() if ctl.is_file() else 'SUCCEEDED'
Path(sys.argv[2], 'lec.rpt').write_text('points\\n')
print('Verification ' + res)
print('  12 Passing compare points' if res == 'SUCCEEDED' else '  3 Failing compare points')
"""
# PrimeTime: setup met once a timing fix was sourced into the ECO NETLIST
FAKE_PT = """import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
net = Path(re.search(r'read_verilog "([^"]+)"', text).group(1)).read_text()
work = Path(sys.argv[2])
met = 'sta_fix_' in net
(work / 'sta_setup.rpt').write_text('  Startpoint: o_y_reg_0_\\n  Endpoint: o_y_reg_0_\\n  slack (%s)  %s\\n' % (('MET', '0.12') if met else ('VIOLATED', '-0.30')))
(work / 'sta_hold.rpt').write_text('  slack (MET)  0.05\\n')
(work / 'sta_constraints.rpt').write_text('' if met else '   max_delay/setup ('"'"'i_clk'"'"' group)\\n\\n   o_y_reg_0_/D   -0.30 (VIOLATED)\\n')
print('Q3TUI_STA: DONE')
"""


class EcoLLM:
    """The ECO flow's stages: RTL(F) edits blk.sv, the patch / timing fix are fixed edits, an EQ advice blames the patch."""
    def __init__(self):
        self.first_patch = None  # (a first answer that is refused: the stage answers again with `patch`)
        self.alt = None  # (the plan of eco_rtl finds this smaller change than the one asked)
        self.stages, self.same, self.patch = [], False, ["disconnect_net o_r U2/Z", "create_cell U3 gf/TIEL_X1", "connect_net o_r U3/ZN"]
        self.concerns = {}  # (stage name -> the concerns its first answer reports)

    async def __call__(self, stage, cfg, emit):
        from q3tui.llm.runtime import StageResult
        self.stages.append(stage)
        if stage.name == "eco_rtl_plan":
            out = RtlPlan(requested="a new TIEL cell drives o_r" if self.alt else "", plan="tie o_r low", netlist_impact="one tie cell",
                          alternative=self.alt)
        elif stage.name == "eco_rtl":
            f = stage.write_dirs[0] / "blk.sv"
            f.write_text(f.read_text().replace("assign o_r = 1'b1;", "assign o_r = 1'b0;")
                         + ("" if self.same or "## Change requests" not in stage.prompt else f"// rev {len(self.stages)}\n"))
            out = RtlUpdate(summary="o_r is now 0", changes=[{"file": "eco/rtl/blk.sv", "what": "o_r tied low"}])
        elif stage.name == "eco_spec":
            f = stage.write_dirs[0] / "spec.md"
            f.write_text(f.read_text().replace("o_r is always 1.", "o_r is always 0 (ECO)."))
            out = RtlUpdate(summary="o_r is 0 in the spec", changes=[{"file": "spec/spec.md", "what": "o_r"}])
        elif stage.name == "eco_patch":  # (a revision is a different patch, unless `same`)
            rev = [] if self.same or "## Revise" not in stage.prompt else [f"set eco_rev {len(self.stages)}"]
            first = self.first_patch if self.first_patch and "previous answer was refused" not in stage.prompt else None
            out = NetlistEdits(commands=first or [*self.patch, *rev], notes="tie o_r low")
        elif stage.name == "eco_sta_fix":
            out = NetlistEdits(commands=["size_cell U1 gf/MUX2_X4"], notes="upsize the mux")
        else:
            out = EqAdvice(summary="o_r still driven by the TIEH cell.", owner="patch", fix="disconnect U2 from o_r")
        if isinstance(out, RtlUpdate):
            out.concerns = self.concerns.pop(stage.name, [])
        return StageResult("ok", out, 0.0, 1, "s")


@pytest.fixture(autouse=True)
def llm(monkeypatch):
    from q3tui.llm import runtime
    fake = EcoLLM()
    monkeypatch.setattr(runtime, "run_stage", fake)
    return fake


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "src" / "rtl").mkdir(parents=True)
    (tmp_path / "src" / "rtl" / "blk.sv").write_text(RTL)
    (tmp_path / "src" / "rtl" / "filelist.f").write_text("src/rtl/blk.sv\n")
    (tmp_path / "schemas").mkdir()
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "spec.md").write_text(SPEC)
    (tmp_path / "schemas" / "structured_spec.json").write_text(json.dumps({"metadata": {"top_module": "blk"}}))
    net = tmp_path / "build" / "syn" / "asic" / "netlist"
    net.mkdir(parents=True)
    (net / "blk.v").write_text(NETLIST)
    (net / "blk.sdc").write_text("create_clock -period 5 [get_ports i_clk]\n")
    (tmp_path / "eco").mkdir()
    (tmp_path / "eco" / "requirement.md").write_text("# ECO\no_r must be 0.\n")
    (tmp_path / "lib.db").write_text("fake library\n")
    for n, text in (("fake_dc.py", FAKE_DC), ("fake_fm.py", FAKE_FM), ("fake_pt.py", FAKE_PT)):
        (tmp_path / n).write_text(text)
    cmd = lambda n: f"\"{sys.executable} {tmp_path / n} {{script}} {{workdir}}\""  # noqa: E731
    (tmp_path / "q3tui.yaml").write_text(
        "pipeline:\n  flow: eco\n  step_options:\n    eco_verify:\n      verify: 'no'\n    eco_inputs:\n      library: " + str(tmp_path / "lib.db") + "\n"
        "tools:\n  roles:\n"
        f"    asic_synth:\n      cmd: {cmd('fake_dc.py')}\n      parse: generic\n"
        f"    asic_lec:\n      cmd: {cmd('fake_fm.py')}\n      parse: generic\n"
        f"    eco_sta:\n      cmd: {cmd('fake_pt.py')}\n      parse: generic\n")
    return Project.open(tmp_path)


def _open(eng: Engine, step: str) -> list[dict]:
    return [q for q in eng.questions() if q["step"] == step and q["status"] == "open"]


async def _drive(eng: Engine, answers: dict | None = None, rounds: int = 25) -> Engine:
    """Run the flow as a person would: each open question answered with `answers[step]` (a step not listed: its first option), each open
    gate approved, run again — until nothing is left to do."""
    answers = answers or {}
    for _ in range(rounds):
        await eng.run()
        acted = False
        for q in [q for q in eng.questions() if q["status"] == "open"]:
            eng.answer(q["id"], answers.get(q["step"]) or q["options"][0]["label"])
            acted = True
        if eng.pending_approvals():
            eng.approve_all()
            acted = True
        if not acted:
            break
    return eng


# -- pieces --------------------------------------------------------------------------------------------------------------------------------

def test_the_flow_loads():
    flow = flows.load_flow("eco", Path.cwd())
    assert [s.id for s in flow.steps] == ["eco_inputs", "eco_eq1", "eco_spec", "eco_rtl", "eco_verify", "eco_patch", "eco_apply", "eco_eq2",
                                          "eco_sta"]
    assert {s.id: s.gate for s in flow.steps}["eco_rtl"] == "human" and "eco_sta" in flow.tools


def test_your_paths_are_read_from_the_answer():
    assert parse_paths("rtl=a/f.f netlist=/x/n.v, requirement='r q.md'") == {"rtl": "a/f.f", "netlist": "/x/n.v", "requirement": "r q.md"}
    assert parse_paths("Use the defaults") == {}


def test_the_guard_takes_netlist_edits_only():
    assert tcl.check_edits(["create_cell U9 lib/INV_X1", "connect_net n1 [get_pins U9/I]", "# a note", ""]) == []
    bad = tcl.check_edits(["exec rm -rf /", "connect_net n1 [exec ls]", "size_cell U1 X; exec ls", "foreach c {a} {remove_cell $c}",
                           "source /tmp/x.tcl", "redirect /tmp/x {report_timing}"])
    assert len(bad) == 6 and "exec" in bad[0]


def test_the_scripts():
    s = tcl.apply_script(["/l/a.db"], Path("/n/org.v"), "blk", [Path("/p/eco_patch.tcl"), Path("/p/sta_fix_1.tcl")], Path("/o/blk.v"), Path("/w"))
    assert s.index("read_verilog -netlist") < s.index("\nlink\n") < s.index("eco_patch.tcl") < s.index("sta_fix_1.tcl") < s.index("write -format verilog")
    assert "compile" not in s
    p = tcl.sta_script(["/l/a.db"], Path("/o/blk.v"), "blk", Path("/n/blk.sdc"), Path("/w"))
    assert "link_design blk" in p and 'read_sdc -echo "/n/blk.sdc"' in p and "-delay_type max" in p and "-delay_type min" in p
    assert 'source -echo "/c/sdc.tcl"' in tcl.sta_script([], Path("/o.v"), "blk", Path("/c/sdc.tcl"), Path("/w"))


def test_the_sta_result():
    r = tcl.sta_result("slack (VIOLATED)  -0.30\n", "slack (MET) 0.1\n", "   max_delay/setup ('clk' group)\n\n   r/D   -0.30 (VIOLATED)\n")
    assert r["setup_ok"] is False and r["setup"]["slack_ns"] == -0.3 and len(r["setup_violations"]) == 1 and not r["hold_violations"]
    assert tcl.sta_result("slack (MET)  0.2\n", "", "")["setup_ok"] is True


def test_edits_that_do_not_fit_the_netlist_are_refused():
    ok = ["create_net n9", "disconnect_net o_r U2/Z", "connect_net n9 U2/Z", "create_cell U3 [get_lib_cells */MUX2_X1]",
          "connect_net n9 U3/I0", "connect_net o_r U3/Z", "size_cell U1 lib/MUX2_X1"]
    assert tcl.check_structure(ok, NETLIST) == []
    # (the first patch of the rv32iv run: a placeholder cell, never connected)
    bad = tcl.check_structure(["create_net p", "disconnect_net o_r U2/Z", "connect_net p U2/Z", "create_cell U3 BWP_PLACEHOLDER",
                               "create_net q", "connect_net o_r U99/Z"], NETLIST)
    assert any("placeholder" in b for b in bad) and any("`U3` is never connected" in b for b in bad)
    assert any("`q` is never connected" in b for b in bad) and any("`U99` is not in the netlist" in b for b in bad)
    assert any("not a library cell" in b for b in tcl.check_structure(["size_cell U1 INV_X9"], NETLIST))


def test_the_cells_of_a_netlist():
    assert tcl.cell_types(NETLIST) == {"DFFRNQ_X1": 1, "MUX2_X1": 1, "TIEH_X1": 1, "TIEL_X1": 1, "MUX2_X4": 1}


def test_eq2_answers_go_to_their_step():
    assert route("Fix the patch (Recommended): x") == "eco_patch" and route("Fix RTL(F): y") == "eco_rtl"
    assert route("o_r should toggle", "eco_patch") == "eco_patch" and route("rtl: o_r is 0", "eco_patch") == "eco_rtl"
    assert route("Stop: I fix it by hand") is None
    assert own_words("My own fix: <type how to fix it>") == "" and own_words("My own fix: tie U3 low") == "tie U3 low"
    assert own_words("disconnect U2") == "disconnect U2"


async def test_the_concerns_of_a_change_are_your_questions(proj, llm):
    # (a concern of eco_spec answered with your words: a change request on the spec; one of eco_rtl kept: RTL(F) stays)
    llm.concerns = {"eco_spec": ["The reset value of o_r is not said."], "eco_rtl": ["U2 is left without a load."]}
    eng = Engine(proj)
    for _ in range(5):  # (the inputs and EQ(1) answered, up to the spec's question)
        await eng.run()
        if _open(eng, "eco_spec"):
            break
        for q in [q for q in eng.questions() if q["status"] == "open"]:
            eng.answer(q["id"], {"eco_inputs": "Use the defaults", "eco_eq1": "Run EQ(1)"}.get(q["step"]) or q["options"][0]["label"])
    [q] = _open(eng, "eco_spec")
    assert q["id"].startswith("ECOC") and "reset value of o_r" in q["question"] and q["blocking"]
    assert not (proj.schemas_dir / "eco_rtl.json").exists()  # (the flow waits for your answer)
    eng = await _drive(eng, {"eco_spec": "My answer: o_r is 0 from reset on.", "eco_rtl": "Keep the change (Recommended)"})
    assert all(v.status == "done" for v in _status(eng).values()), [(v.name, v.status, v.detail) for v in _status(eng).values()]
    specs = [s for s in llm.stages if s.name == "eco_spec"]
    assert len(specs) == 2 and "o_r is 0 from reset on." in specs[1].prompt and "## Change requests" in specs[1].prompt
    rtl = json.loads((proj.schemas_dir / "eco_rtl.json").read_text())
    assert [a["answer"] for a in rtl["concern_asks"].values()] == ["Keep the change (Recommended)"]
    assert all(a["used"] for a in json.loads((proj.schemas_dir / "eco_spec.json").read_text())["concern_asks"].values())


async def test_eq_reads_a_memory_wrapper_as_its_macro_body(proj):
    # (asic_macro implemented blk.sv with a macro: the netlist has the macro, so EQ(1) / EQ(2) read the ASIC body and the macro's .db)
    body = proj.root / "build" / "syn" / "asic" / "macros" / "blk_sram.sv"
    body.parent.mkdir(parents=True)
    body.write_text(RTL)
    (proj.root / "mem.db").write_text("fake macro library\n")
    (proj.schemas_dir / "asic_macro.json").write_text(json.dumps({"wrappers": {"blk": {
        "file": "src/rtl/blk.sv", "asic_file": "build/syn/asic/macros/blk_sram.sv", "db": "mem.db", "macro": "SRAM"}}}))
    eng = await _drive(Engine(proj), {"eco_inputs": "Use the defaults", "eco_eq1": "Run EQ(1)"})
    assert all(v.status == "done" for v in _status(eng).values())
    for step in ("eco_eq1", "eco_eq2"):
        tcl = (proj.build_dir / "eco" / step / "lec.tcl").read_text()
        assert "blk_sram.sv" in tcl and "mem.db" in tcl and "src/rtl/blk.sv" not in tcl, step


def test_without_a_library_setting_the_one_asic_synth_used_is_read(proj):
    yaml = proj.root / "q3tui.yaml"
    yaml.write_text(yaml.read_text().replace("    eco_inputs:\n      library: " + str(proj.root / "lib.db") + "\n", ""))
    eng = Engine(Project.open(proj.root))
    step = next(s for s in eng.steps if s.kind == "eco.eco_sta")
    assert step.libraries(eng) == []
    (proj.schemas_dir / "asic_synth.json").write_text(json.dumps({"library": [str(proj.root / "lib.db")]}))
    assert step.libraries(eng) == [str(proj.root / "lib.db")]


def test_a_passed_asic_lec_stands_for_eq1(proj):
    rtl = [proj.root / "src" / "rtl" / "blk.sv"]
    inputs = {"netlist": "build/syn/asic/netlist/blk.v"}
    assert lec_reuse(proj, inputs, rtl)[0] is False  # (none)
    (proj.schemas_dir / "asic_lec.json").write_text(json.dumps({"status": "equivalent", "netlist": "build/syn/asic/netlist/blk.v", "passing": 9}))
    assert lec_reuse(proj, inputs, rtl)[0] is True
    assert lec_reuse(proj, {"netlist": "other.v"}, rtl)[0] is False
    (proj.schemas_dir / "asic_lec.json").write_text(json.dumps({"status": "not_equivalent", "netlist": "build/syn/asic/netlist/blk.v"}))
    assert "did not pass" in lec_reuse(proj, inputs, rtl)[1]


# -- the flow -----------------------------------------------------------------------------------------------------------------------------

def _status(eng: Engine) -> dict:
    return {v.name: v for v in eng.status()}


async def test_the_whole_flow(proj, llm):
    eng = await _drive(Engine(proj), {"eco_inputs": "Use the defaults", "eco_eq1": "Run EQ(1)"})
    st = _status(eng)
    assert all(v.status == "done" for v in st.values()), [(v.name, v.status, v.detail) for v in st.values()]
    root = proj.root
    assert (root / "ref" / "blk" / "netlist" / "blk.v").read_text() == NETLIST and (root / "ref" / "blk" / "netlist" / "blk.sdc").is_file()
    assert json.loads((proj.schemas_dir / "eco_eq1.json").read_text())["status"] == "equivalent"
    # (project mode: the project's own RTL and spec are modified; the ORG design is kept in ref/blk/)
    assert "assign o_r = 1'b0;" in (root / "src" / "rtl" / "blk.sv").read_text() and not (root / "eco" / "rtl").exists()
    assert (root / "ref" / "blk" / "src" / "rtl" / "blk.sv").read_text() == RTL and "ref/blk/src/rtl/blk.sv" in (root / "eco" / "rtl.diff").read_text()
    assert "o_r is always 0 (ECO)." in (root / "spec" / "spec.md").read_text() and (root / "ref" / "blk" / "spec" / "spec.md").read_text() == SPEC
    assert "+o_r is always 0 (ECO)." in (root / "eco" / "spec.diff").read_text()
    ref = json.loads((root / "eco" / "ref.json").read_text())
    assert ref["mode"] == "project" and ref["path"] == "ref/blk" and json.loads((proj.schemas_dir / "eco_verify.json").read_text())["status"] == "skipped"
    assert "connect_net o_r U3/ZN" in (root / "eco" / "patch" / "eco_patch.tcl").read_text()
    assert json.loads((proj.schemas_dir / "eco_eq2.json").read_text())["status"] == "equivalent"
    sta = json.loads((proj.schemas_dir / "eco_sta.json").read_text())
    assert sta["status"] == "pass" and sta["fixes"] == ["eco/patch/sta_fix_1.tcl"]  # (setup violated once: one timing fix, applied, checked)
    assert "sta_fix_1.tcl" in (root / "eco" / "netlist" / "blk.v").read_text() and "PASS" in (root / "eco" / "reports" / "sta.md").read_text()
    names = [s.name for s in llm.stages]
    assert names.count("eco_sta_fix") == 1 and names.count("eco_eq2_advice") == 0
    rtl_stage = next(s for s in llm.stages if s.name == "eco_rtl")
    assert rtl_stage.write_dirs == [root / "src" / "rtl"] and root / "build" in rtl_stage.deny_dirs
    assert "## The spec update of this ECO" in rtl_stage.prompt


async def test_every_step_has_a_report_in_the_tui(proj, tmp_path):
    from types import SimpleNamespace
    from q3tui.flows.eco import panels
    from q3tui.tui.panels import PANELS
    assert {f"eco.{s}" for s in panels.STEPS} <= set(PANELS) and list(panels.STEPS) == [s.name for s in Engine(proj).steps]
    app = SimpleNamespace(project=proj)
    assert all(rows(app) == [] and brief(app) == panels.NOT_RUN for _, brief, rows, *_ in panels.STEPS.values())  # (not run yet: no rows)
    await _drive(Engine(proj), {"eco_inputs": "Use the defaults", "eco_eq1": "Run EQ(1)"})
    briefs = {name: brief(app) for name, (_, brief, *_) in panels.STEPS.items()}
    assert briefs["eco_eq2"][1] == "pass" and briefs["eco_sta"][1] == "pass" and briefs["eco_verify"][1] == "skip", briefs
    assert "new cell(s)" in briefs["eco_patch"][0]
    for name, (_, _, rows, detail, _) in panels.STEPS.items():
        got = rows(app)
        assert got and all(len(r) == 4 for r in got), name
        assert all(isinstance(detail(app, r[0]), str) and detail(app, r[0]) for r in got), name  # (every row opens a detail)
    assert "```diff" in panels.STEPS["eco_rtl"][3](app, "diff") and "o_r" in panels.STEPS["eco_rtl"][3](app, "diff")
    assert "```tcl" in panels.STEPS["eco_patch"][3](app, "cmds") and "connect_net o_r U3/ZN" in panels.STEPS["eco_patch"][3](app, "cmds")
    assert [r[0] for r in panels._overview_rows(app)] == list(panels.STEPS) and panels._overview_summary(app).startswith("9/9 steps done")
    tasks = json.loads((proj.schemas_dir / "eco_tasks.json").read_text())
    for step in Engine(proj).steps:  # (the Tasks tab: one row per task, each with a detail; every task of a passed run recorded)
        [tab] = [t for t in panels._tabs_for(step.name, step) if t.id == "tasks"]
        got = tab.rows(app)
        assert [r[0] for r in got] == [n for n, _ in step.tasks] and all(len(r) == 5 and tab.detail(app, r[0]) for r in got), step.name
        assert step.name in tasks, step.name
    assert tasks["eco_rtl"]["plan"]["status"] == "done" and tasks["eco_eq2"]["formality"]["status"] == "done"


async def test_an_unattended_eco_answers_the_dv_flows_questions(proj, monkeypatch):
    # (--yes: the dv / Sanity run inside eco_verify takes the defaults of its blocking questions, as the ECO goes on without you)
    from types import SimpleNamespace
    from q3tui.flows.eco.eco_verify.dv import task as dv
    seen = []

    async def fake_run(self, yes=False, **kw):
        seen.append((yes, self.project.cfg.pipeline.auto_answer))
        return "complete"
    monkeypatch.setattr(Engine, "run", fake_run)
    eng = Engine(Project.open(proj.root))
    ctx = SimpleNamespace(engine=eng, project=eng.project)
    assert await dv.other(ctx, "dv", True) == "complete" and await dv.other(ctx, "dv", False) == "complete"
    assert seen == [(True, True), (False, False)] and eng.project.cfg.pipeline.auto_answer is False


def test_every_task_is_a_folder_of_its_step():
    # (workflow flows/eco/ → step <step>/ → task <step>/<task>/task.py, prompt.md for an LLM call; no prompt left in skill.md)
    root = Path(flows.__file__).parent / "eco"
    steps = {s.name: s for s in flows.build_steps(flows.load_flow("eco"))}
    assert [t for t, _ in steps["eco_rtl"].tasks] == ["check_requirement", "plan", "decide", "edit", "concerns", "check"]
    assert [t for t, _ in steps["eco_apply"].tasks] == ["dc"]
    for name, step in steps.items():
        assert step.tasks, name
        for task, about in step.tasks:
            assert (root / name / task / "task.py").is_file() and about, (name, task)
        assert "<!-- " not in (root / name / "md" / "skill.md").read_text(), name
    prompts = sorted(str(p.relative_to(root)) for p in root.glob("*/*/prompt.md"))
    assert prompts == ["eco_eq1/advise/prompt.md", "eco_eq2/advise/prompt.md", "eco_patch/edits/prompt.md", "eco_rtl/edit/prompt.md",
                       "eco_rtl/plan/prompt.md", "eco_spec/edit/prompt.md", "eco_sta/fix/prompt.md"], prompts
    assert (root / "TASKS.md").read_text().count("| `") == sum(len(s.tasks) for s in steps.values())  # (TASKS.md: one line per task)


async def test_it_asks_for_the_inputs_first(proj):
    eng = Engine(proj)
    await eng.run()
    [q] = _open(eng, "eco_inputs")
    assert q["blocking"] and "build/syn/asic/netlist/blk.v" in q["question"] and _status(eng)["eco_eq1"].status != "done"


async def test_unattended_takes_the_first_option(proj):
    eng = Engine(proj)
    await eng.run(yes=True)
    st = _status(eng)
    assert all(v.status == "done" for v in st.values()), [(v.name, v.status, v.detail) for v in st.values()]
    assert json.loads((proj.schemas_dir / "eco_inputs.json").read_text())["how"] == "defaults"
    assert json.loads((proj.schemas_dir / "eco_eq1.json").read_text())["source"] == "formality"


async def test_eq1_skipped_goes_on(proj):
    eng = await _drive(Engine(proj), {"eco_eq1": "Skip EQ(1)"})
    assert json.loads((proj.schemas_dir / "eco_eq1.json").read_text())["status"] == "skipped"
    assert _status(eng)["eco_sta"].status == "done"


async def test_eq1_offers_the_asic_lec_result(proj):
    (proj.schemas_dir / "asic_lec.json").write_text(json.dumps({"status": "equivalent", "netlist": "build/syn/asic/netlist/blk.v", "passing": 9}))
    eng = Engine(proj)
    await _drive(eng, {"eco_eq1": "Use the asic_lec result"})
    eq1 = json.loads((proj.schemas_dir / "eco_eq1.json").read_text())
    assert eq1["status"] == "equivalent" and eq1["source"] == "asic_lec"
    assert "asic_lec passed" in eng.state.closed_questions["eco_eq1"][eq1["question"]]["question"]


async def test_eq1_failing_stops_with_a_report(proj):
    (proj.root / "fm_result.txt").write_text("FAILED")
    eng = await _drive(Engine(proj))
    st = _status(eng)
    assert st["eco_eq1"].status == "failed" and "eco/reports/eq1.md" in st["eco_eq1"].detail and st["eco_rtl"].status != "done"
    assert "FAILED" in (proj.root / "eco" / "reports" / "eq1.md").read_text()


async def test_your_own_paths(proj):
    other = proj.root / "other"
    other.mkdir()
    (other / "n.v").write_text(NETLIST)
    (other / "req.md").write_text("o_r must be 0\n")
    await _drive(Engine(proj), {"eco_inputs": "rtl=src/rtl/filelist.f netlist=other/n.v requirement=other/req.md"})
    inp = json.loads((proj.schemas_dir / "eco_inputs.json").read_text())
    assert inp["source"]["netlist"] == "other/n.v" and inp["how"] == "your paths" and inp["org_sdc"] is None


async def test_eq2_failing_asks_you_and_sends_the_fix(proj, llm):
    eng = await _drive(Engine(proj))
    (proj.root / "fm_result.txt").write_text("FAILED")
    eng.request_change("eco_patch", "try again")
    eng.approve_all()
    for _ in range(4):
        await eng.run()
        if _open(eng, "eco_eq2"):
            break
        eng.approve_all()
    [q] = _open(eng, "eco_eq2")
    assert q["blocking"] and q["options"][0]["label"].startswith("Fix the patch (Recommended)") and "Recommended:" in q["question"] and (proj.root / "eco" / "reports" / "eq2.md").is_file()
    (proj.root / "fm_result.txt").write_text("SUCCEEDED")
    eng.answer(q["id"], q["options"][0]["label"])
    await _drive(eng)
    assert any("From eco_eq2" in s.prompt for s in llm.stages if s.name == "eco_patch")
    assert json.loads((proj.schemas_dir / "eco_eq2.json").read_text())["status"] == "equivalent"


async def test_a_patch_that_does_not_apply_goes_back_to_eco_patch(proj, llm):
    llm.patch = ["set eco_note BAD"]  # (fits the netlist; the fake Design Compiler refuses it)
    eng = await _drive(Engine(proj))
    st = _status(eng)
    assert st["eco_apply"].status == "failed" and "after" in st["eco_apply"].detail  # (every round the same refused patch)
    prompts = [s.prompt for s in llm.stages if s.name == "eco_patch"]
    assert len(prompts) >= 2 and "Cannot find cell 'BAD'" in prompts[-1]


async def test_a_revision_with_the_same_edits_fails(proj, llm):
    llm.patch, llm.same = ["set eco_note BAD"], True
    eng = await _drive(Engine(proj))
    st = _status(eng)
    assert st["eco_patch"].status == "failed" and "same edits" in st["eco_patch"].detail


async def _eq2_fails(eng: Engine, proj) -> dict:
    """EQ(2) fails once (a new patch is asked for, Formality says FAILED): its question."""
    (proj.root / "fm_result.txt").write_text("FAILED")
    eng.request_change("eco_patch", "try again")
    eng.approve_all()
    for _ in range(4):
        await eng.run()
        if _open(eng, "eco_eq2"):
            break
        eng.approve_all()
    [q] = _open(eng, "eco_eq2")
    (proj.root / "fm_result.txt").write_text("SUCCEEDED")
    return q


async def test_eq2_takes_your_own_fix(proj, llm):
    eng = await _drive(Engine(proj))
    q = await _eq2_fails(eng, proj)
    assert any(o["label"].startswith("My own fix") for o in q["options"])
    eng.answer(q["id"], "keep U2, drive o_r from a new TIEL cell")
    await _drive(eng)
    last = [s.prompt for s in llm.stages if s.name == "eco_patch"][-1]  # (the analysis blames the patch: your words go there)
    assert "the user's fix: keep U2, drive o_r from a new TIEL cell" in last and "The analysis' fix" in last
    assert json.loads((proj.schemas_dir / "eco_eq2.json").read_text())["status"] == "equivalent"


async def test_eq2_under_auto_answer_sends_the_recommended_fix(proj, llm):
    eng = await _drive(Engine(proj))
    proj.cfg.pipeline.auto_answer = True
    (proj.root / "fm_result.txt").write_text("FAILED")
    seen = []
    eng.bus.subscribe(lambda e: e.kind == "warning" and e.step == "eco_eq2" and seen.append(e.data["message"]))
    eng.request_change("eco_patch", "try again")
    await eng.run()  # (auto-answer: the gates approve, EQ(2) asks nobody; still FAILED: the bound stops it)
    assert not _open(eng, "eco_eq2") and any("recommended fix to eco_patch (auto-answer" in m for m in seen)
    assert any("From eco_eq2 (EQ(2) failed, auto-answer): Fix the patch (Recommended)" in s.prompt for s in llm.stages if s.name == "eco_patch")
    assert "Auto-answer round 1: the recommended fix went to `eco_patch`" in (proj.root / "eco" / "reports" / "eq2.md").read_text()
    assert _status(eng)["eco_eq2"].status == "failed" and "round(s) of fixes" in _status(eng)["eco_eq2"].detail


async def test_eq2_fix_rtl_goes_back_to_eco_rtl_and_on(proj, llm):
    eng = await _drive(Engine(proj))
    q = await _eq2_fails(eng, proj)
    rtl_opt = next(o["label"] for o in q["options"] if o["label"].startswith("Fix RTL(F)"))
    before = len(llm.stages)
    eng.answer(q["id"], rtl_opt)
    await _drive(eng)
    after = [s.name for s in llm.stages[before:]]
    assert after.index("eco_rtl") < after.index("eco_patch")  # (RTL(F) first, then a new patch for it)
    assert "From eco_eq2" in next(s.prompt for s in llm.stages[before:] if s.name == "eco_rtl")
    assert "// rev" in (proj.root / "eco" / "rtl.diff").read_text()
    st = _status(eng)
    assert all(v.status == "done" for v in st.values()), [(v.name, v.status, v.detail) for v in st.values()]
    assert json.loads((proj.schemas_dir / "eco_eq2.json").read_text())["status"] == "equivalent"


async def test_an_rtl_revision_that_changes_nothing_fails(proj, llm):
    eng = await _drive(Engine(proj))
    q = await _eq2_fails(eng, proj)
    llm.same = True
    eng.answer(q["id"], next(o["label"] for o in q["options"] if o["label"].startswith("Fix RTL(F)")))
    await _drive(eng)
    st = _status(eng)
    assert st["eco_rtl"].status == "failed" and "same as before" in st["eco_rtl"].detail


async def test_a_refused_patch_is_written_again_with_the_reasons(proj, llm):
    llm.first_patch = ["disconnect_net o_r U2/Z", "create_cell U3 BWP_PLACEHOLDER"]  # (as the first patch of the rv32iv run)
    eng = await _drive(Engine(proj))
    prompts = [s.prompt for s in llm.stages if s.name == "eco_patch"]
    assert len(prompts) == 2 and "placeholder" in prompts[1] and "`U3` is never connected" in prompts[1]
    assert "BWP_PLACEHOLDER" not in (proj.root / "eco" / "patch" / "eco_patch.tcl").read_text()
    assert _status(eng)["eco_sta"].status == "done"


ALT = RtlAlternative(change="assign o_r = ~1'b1", smaller_because="no new cell", same_function_because="o_r is 0 either way",
                     differs_from_request="no TIEL cell in the RTL")


async def test_rtl_plan_without_a_smaller_way_asks_nothing(proj, llm):
    eng = await _drive(Engine(proj))
    assert not [q for q in eng.questions() if q["step"] == "eco_rtl"]
    edit = next(s for s in llm.stages if s.name == "eco_rtl")
    assert "## The change to make" in edit.prompt and "tie o_r low" in edit.prompt
    assert not (proj.schemas_dir / "eco_rtl_plan.json").is_file()  # (done: cleared)


@pytest.mark.parametrize("answer, expect", [("Use the smaller change", "assign o_r = ~1'b1"), ("Keep the change as asked", "a new TIEL cell"),
                                            ("My own way: assign o_r = 1'b0 directly", "assign o_r = 1'b0 directly")])
async def test_a_smaller_change_than_asked_is_your_decision(proj, llm, answer, expect):
    llm.alt = ALT
    eng = Engine(proj)
    for _ in range(6):  # (to the eco_rtl question, nothing edited before it)
        await eng.run()
        if _open(eng, "eco_rtl"):
            break
        for q in [q for q in eng.questions() if q["status"] == "open"]:
            eng.answer(q["id"], q["options"][0]["label"])
        eng.approve_all()
    [q] = _open(eng, "eco_rtl")
    assert q["blocking"] and q["options"][0]["label"].startswith("Use the smaller change (Recommended)") and "no new cell" in q["question"]
    assert not any(s.name == "eco_rtl" for s in llm.stages)
    eng.answer(q["id"], answer)
    await _drive(eng)
    edit = next(s for s in llm.stages if s.name == "eco_rtl")
    assert expect in edit.prompt
    assert json.loads((proj.schemas_dir / "eco_rtl.json").read_text())["change"]
    assert [s.name for s in llm.stages].count("eco_rtl_plan") == 1  # (the plan is not made again for the answer)


async def test_auto_answer_takes_the_smaller_change(proj, llm):
    llm.alt = ALT
    eng = Engine(proj)
    await eng.run(yes=True)
    assert not [q for q in eng.questions() if q["step"] == "eco_rtl"]
    assert "assign o_r = ~1'b1" in next(s for s in llm.stages if s.name == "eco_rtl").prompt


async def test_a_change_request_is_kept_while_its_question_waits(proj, llm):
    eng = await _drive(Engine(proj))
    llm.alt = ALT
    eng.request_change("eco_rtl", "drive o_r from a new TIEL cell")
    await eng.run()
    [q] = _open(eng, "eco_rtl")
    eng.answer(q["id"], "Keep the change as asked")
    await _drive(eng)
    edit = [s for s in llm.stages if s.name == "eco_rtl"][-1]
    assert "## Change requests on the current RTL(F)" in edit.prompt and "drive o_r from a new TIEL cell" in edit.prompt


async def test_the_svf_beside_the_netlist_guides_both_eqs(proj, llm):
    (proj.root / "build" / "syn" / "asic" / "netlist" / "blk.svf").write_bytes(b"svf")
    await _drive(Engine(proj), {"eco_inputs": "Use the defaults", "eco_eq1": "Run EQ(1)"})
    svf = proj.root / "ref" / "blk" / "netlist" / "blk.svf"
    assert svf.read_bytes() == b"svf"
    for step in ("eco_eq1", "eco_eq2"):
        assert f'set_svf "{svf}"' in (proj.build_dir / "eco" / step / "lec.tcl").read_text()


async def test_an_org_rtl_outside_the_project_with_a_hard_macro(proj, llm, tmp_path_factory):
    # (the ORG RTL as synthesized: outside the project, and a hard macro that has only a .db: pyslang says `unknown module`)
    org = tmp_path_factory.mktemp("eco_input")
    (org / "blk.sv").write_text(RTL.replace("endmodule", "  SRAM_MACRO u_mem (.CLK(i_clk));\nendmodule"))
    (org / "filelist.f").write_text("blk.sv\n")
    proj.cfg.pipeline.step_options.setdefault("eco_inputs", {})["rtl"] = str(org / "filelist.f")
    eng = await _drive(Engine(proj), {"eco_inputs": "Use the defaults", "eco_eq1": "Run EQ(1)"})
    assert _status(eng)["eco_rtl"].status == "done", _status(eng)["eco_rtl"].detail
    plan = next(s for s in llm.stages if s.name == "eco_rtl_plan")
    assert "eco/rtl/blk.sv" in plan.prompt and str(org) not in plan.prompt  # (the plan reads the copies: the sandbox is the project)
    # (external mode, a fire-fighting ECO: the RTL files copied to ref/, no spec update, no dv / Sanity; the project's RTL and spec untouched)
    root = proj.root
    assert json.loads((root / "eco" / "ref.json").read_text())["mode"] == "external" and (root / "ref" / "blk" / "rtl" / "blk.sv").is_file()
    assert (root / "ref" / "blk" / "rtl.f").read_text() == "ref/blk/rtl/blk.sv\n"
    assert json.loads((proj.schemas_dir / "eco_spec.json").read_text())["status"] == "skipped" and "eco_spec" not in [s.name for s in llm.stages]
    assert json.loads((proj.schemas_dir / "eco_verify.json").read_text())["status"] == "skipped"
    assert (root / "src" / "rtl" / "blk.sv").read_text() == RTL and (root / "spec" / "spec.md").read_text() == SPEC
    assert all(v.status == "done" for v in _status(eng).values()), [(v.name, v.status, v.detail) for v in _status(eng).values()]


def test_the_tui_background_run_keeps_the_config_it_was_opened_with(tmp_path, monkeypatch):
    # (without it the run reads only the project's q3tui.yaml: other inputs, auto-answer)
    from q3tui.core.project import Project
    from q3tui.tui.runner import Runner
    (tmp_path / "q3tui.yaml").write_text("pipeline: {auto_answer: true}\n")
    (tmp_path / "eco").mkdir()
    (tmp_path / "eco" / "my.yaml").write_text("pipeline: {flow: eco, auto_answer: false}\n")
    monkeypatch.chdir(tmp_path)
    p = Project.open(tmp_path, Path("eco/my.yaml"))
    cmd = Runner().command(p, "eco")
    assert cmd[cmd.index("--config") + 1] == str((tmp_path / "eco" / "my.yaml").resolve()) and "--auto-answer" not in cmd
    assert "--config" not in Runner().command(Project.open(tmp_path), "eco")


# -- the team version: ref/, project mode, eco_spec, eco_verify ---------------------------------------------------------------------------

def test_a_ref_name_taken_gets_the_date_and_time(proj):
    from datetime import datetime
    from q3tui.flows.eco.lib import ref
    assert ref.unique_dir(proj, "blk") == proj.root / "ref" / "blk"
    (proj.root / "ref" / "blk").mkdir(parents=True)
    assert ref.unique_dir(proj, "blk", datetime(2026, 11, 18, 9, 30, 12)) == proj.root / "ref" / "blk_18112026_093012"
    assert ref.clean_name("My own name: name=pwm_v1") == "pwm_v1" and ref.clean_name("pwm v2/") == "v2"
    assert ref.mode_of(proj, proj.root / "src" / "rtl" / "filelist.f") == "project" and ref.mode_of(proj, Path("/x/f.f")) == "external"


async def test_your_ref_name_and_a_reset_never_snapshots_again(proj, llm):
    (proj.root / "ref" / "pwm_v1").mkdir(parents=True)  # (taken: the ECO gets the name with the date and time)
    proj.cfg.pipeline.step_options["eco_inputs"].update(rtl="src/rtl/filelist.f", netlist="build/syn/asic/netlist/blk.v", requirement="eco/requirement.md")
    eng = await _drive(Engine(proj), {"eco_inputs": "My own name: name=pwm_v1", "eco_eq1": "Run EQ(1)"})
    rec = json.loads((proj.root / "eco" / "ref.json").read_text())
    assert rec["path"].startswith("ref/pwm_v1_") and (proj.root / rec["path"] / "src" / "rtl" / "blk.sv").read_text() == RTL
    assert "assign o_r = 1'b0;" in (proj.root / "src" / "rtl" / "blk.sv").read_text()
    eng.reset("eco_inputs")
    await _drive(eng, {"eco_eq1": "Run EQ(1)"})
    assert json.loads((proj.root / "eco" / "ref.json").read_text()) == rec  # (the modified project is never taken as the ORG design)
    assert sorted(p.name for p in (proj.root / "ref").iterdir()) == ["pwm_v1", rec["name"]]
    assert (proj.root / rec["path"] / "src" / "rtl" / "blk.sv").read_text() == RTL


def _verify_yes(proj, monkeypatch, dv, sanity) -> Engine:
    """An engine whose eco_verify asks (no `verify` option) and runs these stand-ins for the dv and Sanity flows. (The class the engine loads
    from the step's file, not an import of it.)"""
    proj.cfg.pipeline.step_options["eco_verify"] = {}
    eng = Engine(proj)
    cls = type(eng.by_name["eco_verify"])
    monkeypatch.setattr(cls, "_dv", dv)
    monkeypatch.setattr(cls, "_sanity", sanity)
    return eng


async def test_dv_and_sanity_must_pass_before_the_netlist_eco(proj, llm, monkeypatch):
    calls = []

    async def dv(self, ctx, yes):
        calls.append("dv")
        return True, "3 test(s) passed"

    async def sanity(self, ctx, yes):
        calls.append("sanity")
        return True, "nothing open"
    eng = _verify_yes(proj, monkeypatch, dv, sanity)
    for _ in range(10):  # (as _drive, but the verify question is left open)
        await eng.run()
        if _open(eng, "eco_verify"):
            break
        for x in [x for x in eng.questions() if x["status"] == "open"]:
            eng.answer(x["id"], {"eco_eq1": "Run EQ(1)"}.get(x["step"]) or x["options"][0]["label"])
        eng.approve_all()
    [q] = _open(eng, "eco_verify") or [None]
    assert q and q["blocking"] and "dv flow" in q["question"] and _status(eng)["eco_patch"].status == "missing_input" and not calls
    await _drive(eng, {"eco_verify": q["options"][0]["label"]})
    assert calls == ["dv", "sanity"] and json.loads((proj.schemas_dir / "eco_verify.json").read_text())["status"] == "passed"
    assert all(v.status == "done" for v in _status(eng).values()), [(v.name, v.status, v.detail) for v in _status(eng).values()]


async def test_a_dv_rtl_fix_comes_back_to_eco_rtl_then_dv_again(proj, llm, monkeypatch):
    runs = []

    async def dv(self, ctx, yes):  # (first run: a failing test, its RTL fix handed to eco_rtl as the dv triage does during an ECO)
        runs.append(1)
        if len(runs) == 1:
            ctx.engine.request_change("eco_rtl", "[rtl:blk] From the simulation (TC-001): o_r must also be 0 after reset")
            return False, "ended 'failed'"
        return True, "3 test(s) passed"

    async def sanity(self, ctx, yes):
        return True, "nothing open"
    eng = await _drive(_verify_yes(proj, monkeypatch, dv, sanity), {"eco_inputs": "Use the defaults", "eco_eq1": "Run EQ(1)"})
    assert len(runs) == 2 and json.loads((proj.schemas_dir / "eco_verify.json").read_text())["status"] == "passed"
    plans = [s for s in llm.stages if s.name == "eco_rtl_plan"]
    assert len(plans) == 2 and "TC-001" in plans[1].prompt and "## Change requests on this RTL(F)" in plans[1].prompt
    assert _status(eng)["eco_sta"].status == "done"


async def test_a_fix_eco_rtl_judges_not_the_ecos_stops_verify(proj, llm, monkeypatch):

    async def dv(self, ctx, yes):  # (it keeps failing: the testbench is wrong, the RTL is right)
        if "eco_rtl" not in ctx.engine.state.feedback:
            ctx.engine.request_change("eco_rtl", "[rtl:blk] From the simulation (TC-002): o_r must be 1")
        return False, "ended 'failed'"

    async def sanity(self, ctx, yes):
        return True, "nothing open"
    orig = llm.__call__

    async def judging(stage, cfg, emit):
        if stage.name == "eco_rtl_plan" and "TC-002" in stage.prompt:
            from q3tui.llm.runtime import StageResult
            llm.stages.append(stage)
            return StageResult("ok", RtlPlan(plan="No RTL change: the requirement asks o_r = 0; TC-002 checks the ORG behaviour (a testbench issue)",
                                             netlist_impact="none"), 0.0, 1, "s")
        return await orig(stage, cfg, emit)
    from q3tui.llm import runtime
    monkeypatch.setattr(runtime, "run_stage", judging)
    eng = await _drive(_verify_yes(proj, monkeypatch, dv, sanity), {"eco_inputs": "Use the defaults", "eco_eq1": "Run EQ(1)"})
    st = _status(eng)
    assert st["eco_verify"].status == "failed" and "eco_rtl kept the RTL" in st["eco_verify"].detail and "testbench issue" in st["eco_verify"].detail
    assert json.loads((proj.schemas_dir / "eco_rtl.json").read_text())["declined"][0]["requests"][0].endswith("o_r must be 1")
    assert "assign o_r = 1'b0;" in (proj.root / "src" / "rtl" / "blk.sv").read_text() and st["eco_patch"].status != "done"


def test_the_rtl_fixes_of_dv_and_sanity_go_to_the_eco_while_it_is_on(proj):
    from types import SimpleNamespace
    from q3tui.flows.dv.triage import _hand_to_rtl_flow
    from q3tui.flows.eco.lib import ref
    assert ref.eco_owner(proj) is None
    ref.save_pointer(proj, {"mode": "external", "path": "ref/blk"})
    assert ref.eco_owner(proj) is None  # (a fire-fighting ECO: the usual owner)
    ref.save_pointer(proj, {"mode": "project", "path": "ref/blk"})
    assert ref.eco_owner(proj) == "eco" and ref.ECO_STEP == {"rtl": "eco_rtl", "spec": "eco_spec"}
    dv = Engine(proj, flow=flows.load_flow("spec", proj.root))
    assert _hand_to_rtl_flow(SimpleNamespace(engine=dv, project=proj), "eco", "[rtl:blk] fix it", "eco_rtl") == "eco"
    assert Engine(proj).state.feedback["eco_rtl"] == ["[rtl:blk] fix it"]


def test_an_escaped_netlist_name_is_not_a_command():
    from q3tui.flows.eco.lib.tcl import check_edits
    assert check_edits([r"connect_net [get_nets u_core/gen_chan\[0\].u_chan/n1] [get_pins u_core/gen_chan\[0\].u_chan/U3/A1]"]) == []
    assert len(check_edits([r"connect_net n1 [get_pins a\\[exec ls]]"])) == 1  # (`\\[`: a literal backslash, then a real substitution)
    assert len(check_edits([r"connect_net n1 [get_pins a\[0\]] [exec ls]"])) == 1


def test_an_instance_inside_a_submodule_is_found_by_its_path():
    from q3tui.flows.eco.lib.tcl import check_structure
    net = ("module sub ( a, z );\n  input a;\n  output z;\n  INVD1 U7 ( .I(a), .ZN(z) );\nendmodule\n"
           "module top ( a, z );\n  input a;\n  output z;\n  sub u_sub ( .a(a), .z(z) );\nendmodule\n")
    assert check_structure(["disconnect_net [get_nets z] u_sub/U7/ZN"], net) == []
    assert check_structure(["disconnect_net [get_nets z] u_sub/U8/ZN"], net) == ["line 1: instance `u_sub/U8` is not in the netlist"]
    assert check_structure(["disconnect_net [get_nets z] U7/ZN"], net) == ["line 1: instance `U7` is not in the netlist"]  # (not at the top)


def test_a_name_without_its_hierarchy_is_named_from_the_top():
    from q3tui.flows.eco.lib.tcl import check_structure, qualify
    net = ("module sub ( a, z );\n  input a;\n  output z;\n  wire n1;\n  INVD1 U7 ( .I(a), .ZN(n1) );\n  INVD1 U8 ( .I(n1), .ZN(z) );\nendmodule\n"
           "module top ( a, z, y );\n  input a;\n  output z, y;\n  sub u_sub ( .a(a), .z(z) );\n  sub u_two ( .a(a), .z(y) );\n"
           "  INVD1 U9 ( .I(a), .ZN(y) );\nendmodule\n")
    # (U7 / n1 are in both u_sub and u_two: ambiguous, left; in a design with one, they get the path)
    one = net.replace("  sub u_two ( .a(a), .z(y) );\n", "")
    out, notes = qualify(["create_net u_sub/eco_n", "disconnect_net n1 U8/I", "connect_net eco_n U8/I", "connect_net a U9/I"], one)
    assert out == ["create_net u_sub/eco_n", "disconnect_net u_sub/n1 u_sub/U8/I", "connect_net u_sub/eco_n u_sub/U8/I", "connect_net a U9/I"]
    assert len(notes) == 4 and check_structure(out, one) == []
    assert qualify(["disconnect_net n1 U8/I"], net)[0] == ["disconnect_net n1 U8/I"]
    # (a new cell / net made at the top but connected inside u_sub only: made in u_sub; a bare library cell gets its library)
    out, _ = qualify(["create_cell eco_c INVD1", "create_net eco_m", "disconnect_net n1 U8/I", "connect_net eco_m eco_c/ZN",
                      "connect_net eco_m U8/I", "connect_net n1 eco_c/I"], one)
    assert out == ["create_cell u_sub/eco_c [get_lib_cells */INVD1]", "create_net u_sub/eco_m", "disconnect_net u_sub/n1 u_sub/U8/I",
                   "connect_net u_sub/eco_m u_sub/eco_c/ZN", "connect_net u_sub/eco_m u_sub/U8/I", "connect_net u_sub/n1 u_sub/eco_c/I"]
    assert check_structure(out, one) == []
