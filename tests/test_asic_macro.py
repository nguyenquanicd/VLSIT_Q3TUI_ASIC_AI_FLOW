"""The ASIC flow's memory macros (`asic_macro`): the PDK scan (Liberty memory groups, corners, models), the tiling choice, the pin map
check, the ASIC body (compiled by pyslang with a macro model), the lock-step testbench, the step with fake LLM answers and a fake Library
Compiler, and the synthesis / equivalence scripts that take the bodies and the macro libraries."""

import json
import sys
from pathlib import Path

import pytest

from q3tui.core.project import Project
from q3tui.flows.asic.lib import dc, fm, macro
from q3tui.hdl.filelist import filelist_from_files
from q3tui.hdl.parse import parse_design
from q3tui.pipeline.engine import Engine


def _lib(cell: str, words: int, bits: int, area: float, corner: str, period: float = 0.5) -> str:
    aw = (words - 1).bit_length()
    return f"""library ({cell}_{corner}) {{
  time_unit : "1ns" ;
  type ( A_bus ) {{ base_type : array ; bit_width : {aw} ; }}
  type ( D_bus ) {{ base_type : array ; bit_width : {bits} ; }}
  cell ( {cell} ) {{
    area : {area} ;
    memory () {{ type : ram ; address_width : {aw} ; word_width : {bits} ; }}
    pin ( CLK ) {{ direction : input ; clock : true ;
      timing () {{ timing_type : "minimum_period" ; related_pin : "CLK" ;
        rise_constraint ( "t" ) {{ values ( "0.1, {period}" ) ; }} fall_constraint ( "t" ) {{ values ( "0.1, {period}" ) ; }} }} }}
    pin ( CEB ) {{ direction : input ; }}
    pin ( WEB ) {{ direction : input ; }}
    pin ( BIST ) {{ direction : input ; }}
    bus ( A ) {{ bus_type : A_bus ; direction : input ; }}
    bus ( D ) {{ bus_type : D_bus ; direction : input ; }}
    bus ( BWEB ) {{ bus_type : D_bus ; direction : input ; }}
    bus ( Q ) {{ bus_type : D_bus ; direction : output ; }}
  }}
}}
"""


def _model(cell: str, words: int, bits: int) -> str:
    aw = (words - 1).bit_length()
    return f"""// {cell}: CLK clock, CEB chip enable (low), WEB write enable (low), BWEB bit write enable (low), BIST test mux (tie 0)
module {cell} (input CLK, input CEB, input WEB, input BIST, input [{aw - 1}:0] A, input [{bits - 1}:0] D, input [{bits - 1}:0] BWEB, output reg [{bits - 1}:0] Q);
  reg [{bits - 1}:0] mem [0:{words - 1}];
  always @(posedge CLK) if (!CEB) begin
    if (!WEB) mem[A] <= (mem[A] & BWEB) | (D & ~BWEB);
    else Q <= mem[A];
  end
endmodule
"""


def _pdk(root: Path) -> Path:
    """A PDK folder: standard cells (a .db) and two macros (two corners each) with their models."""
    (root / "STD").mkdir(parents=True)
    std = root / "STD" / "cells_tt0p9v25c.db"
    std.write_text("db\n")
    for cell, words, bits, area in (("M64X16", 64, 16, 100.0), ("M256X32", 256, 32, 300.0)):
        d = root / "MEMORY" / "pkg" / "lib" / cell
        d.mkdir(parents=True)
        for corner in ("tt0p9v25c", "ssg0p81v125c"):
            (d / f"{cell}_{corner}.lib").write_text(_lib(cell, words, bits, area, corner))
        v = root / "MEMORY" / "pkg" / "verilog" / cell
        v.mkdir(parents=True)
        (v / f"{cell}_tt0p9v25c.v").write_text(_model(cell, words, bits))
    return std


WRAPPER = """module m_buf_sram #(parameter int W = 32, parameter int D = 512) (
  input  logic                 i_clk,
  input  logic                 i_en,
  input  logic                 i_we,
  input  logic [$clog2(D)-1:0] i_addr,
  input  logic [W/8-1:0]       i_be,
  input  logic [W-1:0]         i_wdata,
  output logic [W-1:0]         o_rdata
);
  logic [W-1:0] reg_mem [D];
  always_ff @(posedge i_clk) if (i_en) begin
    if (i_we) begin for (int b = 0; b < W/8; b++) if (i_be[b]) reg_mem[i_addr][b*8 +: 8] <= i_wdata[b*8 +: 8]; end
    else o_rdata <= reg_mem[i_addr];
  end
endmodule
"""
TOP = """module blk (input logic i_clk, input logic i_en, input logic i_we, input logic [8:0] i_addr, input logic [3:0] i_be,
            input logic [31:0] i_wdata, output logic [31:0] o_rdata);
  m_buf_sram #(.W(32), .D(512)) u_buf (.*);
endmodule
"""
SPEC = macro.MemSpec(words=512, bits=32, ports=[macro.WPort(kind="rw", clk="i_clk", addr="i_addr", din="i_wdata", dout="o_rdata", en="i_en",
                                                              we="i_we", be="i_be")])
PINS = macro.PinMap(ports=[macro.MPort(kind="rw", clk="CLK", addr="A", din="D", dout="Q", en="CEB", we="WEB", bwe="BWEB")], ties={"BIST": "1'b0"})
PORTS = {"i_clk": ("input", 1), "i_en": ("input", 1), "i_we": ("input", 1), "i_addr": ("input", 9), "i_be": ("input", 4), "i_wdata": ("input", 32),
         "o_rdata": ("output", 32)}


# -- code ---------------------------------------------------------------------------------------------------------------

def test_the_scan_finds_the_macros_of_the_corner(tmp_path):
    std = _pdk(tmp_path / "PDK")
    root = macro.pdk_root(str(std))
    assert root == tmp_path / "PDK" and macro.corner_of(str(std)) == "tt0p9v25c"
    found = {m.name: m for m in macro.scan(root, "tt0p9v25c")}
    assert set(found) == {"M64X16", "M256X32"}  # (the .db of the standard cells is not a memory)
    m = found["M256X32"]
    assert (m.words, m.bits, m.addr_bits, m.area, m.corner) == (256, 32, 8, 300.0, "tt0p9v25c")
    assert m.model.endswith("M256X32_tt0p9v25c.v") and m.library == "M256X32_tt0p9v25c"
    assert {x.corner for x in macro.scan(root, "ssg0p81v125c")} == {"ssg0p81v125c"}


def test_liberty_pins_and_period():
    text = _lib("M", 256, 32, 1.0, "tt0p9v25c", period=0.7)
    pins = macro.lib_pins(text)
    assert pins["A"] == ("input", 8) and pins["Q"] == ("output", 32) and pins["CEB"] == ("input", 1)
    assert macro.min_period_ns(text, "CLK") == 0.7


def test_the_smallest_tiling_wins(tmp_path):
    root = tmp_path / "PDK"
    _pdk(root)
    tl = macro.tilings(SPEC, macro.scan(root, "tt0p9v25c"))
    best = tl[0]
    assert (best.macro.name, best.rows, best.cols, best.area) == ("M256X32", 2, 1, 600.0)  # 8 x 2 of M64X16 is 1600
    assert [t.macro.name for t in tl] == ["M256X32", "M64X16"]


def test_a_pin_map_must_cover_every_input(tmp_path):
    root = tmp_path / "PDK"
    _pdk(root)
    m = next(x for x in macro.scan(root, "tt0p9v25c") if x.name == "M256X32")
    pins = macro.lib_pins(Path(m.lib).read_text())
    assert macro.pinmap_problems(PINS, pins, m) == []
    bad = macro.pinmap_problems(PINS.model_copy(update={"ties": {}}), pins, m)
    assert any("BIST" in b for b in bad)
    # a bus tied to all ones: any spelling of a fill is fine for every width of the family; a field must have the pin's width
    wide = {**pins, "BWEBM": ("input", 32)}
    for v in ("{64{1'b1}}", "1'b1", "'1", "32'b" + "1" * 32):
        assert macro.pinmap_problems(PINS.model_copy(update={"ties": {"BIST": "1'b0", "BWEBM": v}}), wide, m) == [], v
        assert macro.tie_expr(v) == "'1"
    assert "32 bits wide" in "".join(macro.pinmap_problems(PINS.model_copy(update={"ties": {"BIST": "1'b0", "BWEBM": "3'b010"}}), wide, m))
    assert macro.fits(SPEC, PINS) == ""
    assert "bit write" in macro.fits(SPEC, PINS.model_copy(update={"ports": [PINS.ports[0].model_copy(update={"bwe": ""})]}))


def test_the_spec_is_checked_against_the_ports():
    assert macro.spec_problems(SPEC, PORTS) == []
    assert any("do not fit" in b for b in macro.spec_problems(SPEC.model_copy(update={"words": 1024}), PORTS))
    assert any("not a port" in b for b in macro.spec_problems(SPEC.model_copy(update={"ports": [SPEC.ports[0].model_copy(update={"en": "i_cs"})]}), PORTS))


def test_the_asic_body_compiles_with_the_macro_model(tmp_path):
    root = tmp_path / "PDK"
    _pdk(root)
    m = next(x for x in macro.scan(root, "tt0p9v25c") if x.name == "M256X32")
    body = macro.render("m_buf_sram", WRAPPER, SPEC, macro.Tiling(m, 2, 1), PINS, PORTS)
    assert "M256X32 u_mem_r0_c0" in body and "M256X32 u_mem_r1_c0" in body and ".BIST('0)" in body and ".CEB(~(" in body
    assert body.startswith("module m_buf_sram #(parameter int W = 32")  # (the wrapper's own header)
    files = [tmp_path / "asic.sv", tmp_path / "top.sv", Path(m.model)]
    files[0].write_text(body)
    files[1].write_text(TOP)
    design = parse_design(filelist_from_files(files), "blk")
    assert design.ok, [d.message for d in design.diagnostics if d.severity == "error"]
    # the check's copy: renamed, alone, and the lock-step testbench compiles with both bodies and the model
    copy = macro.render("m_buf_sram", WRAPPER, SPEC, macro.Tiling(m, 2, 1), PINS, PORTS, name="m_buf_sram_q3asic")
    tb = macro.check_tb("m_buf_sram", "m_buf_sram_q3asic", SPEC, PORTS)
    (tmp_path / "beh.sv").write_text(WRAPPER)
    (tmp_path / "copy.sv").write_text(copy)
    (tmp_path / "tb.sv").write_text(tb)
    design = parse_design(filelist_from_files([tmp_path / "beh.sv", tmp_path / "copy.sv", Path(m.model), tmp_path / "tb.sv"]), "q3_memcheck")
    assert design.ok, [d.message for d in design.diagnostics if d.severity == "error"]
    assert macro.check_result("…\nQ3TUI_MEMCHECK: PASS 0\n") == {"status": "pass", "errors": 0}


def test_a_wide_word_takes_columns_and_a_pad(tmp_path):
    root = tmp_path / "PDK"
    _pdk(root)
    m = next(x for x in macro.scan(root, "tt0p9v25c") if x.name == "M64X16")
    spec = SPEC.model_copy(update={"words": 64, "bits": 24})  # (24 bits on 16-bit macros: 2 columns, 8 bits of pad)
    ports = {**PORTS, "i_addr": ("input", 6), "i_be": ("input", 3), "i_wdata": ("input", 24), "o_rdata": ("output", 24)}
    wrapper = WRAPPER.replace("parameter int W = 32, parameter int D = 512", "parameter int W = 24, parameter int D = 64")
    body = macro.render("m_buf_sram", wrapper, spec, macro.Tiling(m, 1, 2), PINS, ports)
    assert "u_mem_r0_c1" in body and "{8'b0, i_wdata}" in body and "q3_row" not in body
    (tmp_path / "a.sv").write_text(body)
    top = TOP.replace("[8:0] i_addr", "[5:0] i_addr").replace("[3:0] i_be", "[2:0] i_be").replace("[31:0]", "[23:0]").replace("#(.W(32), .D(512))", "#(.W(24), .D(64))")
    (tmp_path / "t.sv").write_text(top)
    design = parse_design(filelist_from_files([tmp_path / "a.sv", tmp_path / "t.sv", Path(m.model)]), "blk")
    assert design.ok, [d.message for d in design.diagnostics if d.severity == "error"]


def test_the_scripts_take_the_macros(tmp_path):
    s = dc.script_text([tmp_path / "a.sv"], "blk", ["/l/cells.db"], None, tmp_path, tmp_path / "n.v", {}, ["/m/M.db"], ["M256X32"])
    assert 'set_app_var target_library [list "/l/cells.db"]' in s and 'link_library [list "*" "/l/cells.db" "/m/M.db"]' in s
    assert 'set_dont_touch [get_cells -hierarchical -filter "ref_name == M256X32"]' in s
    lc = macro.lc_script([("M_tt", "/x/M_tt.lib", tmp_path / "M_tt.db")])
    assert 'read_lib "/x/M_tt.lib"' in lc and f'write_lib M_tt -format db -output "{tmp_path / "M_tt.db"}"' in lc
    data = {"wrappers": {"m_buf_sram": {"file": "src/rtl/m_buf_sram.sv", "asic_file": "a.sv", "db": "M.db", "macro": "M256X32"}}}
    (tmp_path / "a.sv").write_text("x")
    rtl = [tmp_path / "src" / "rtl" / "blk.sv", tmp_path / "src" / "rtl" / "m_buf_sram.sv"]
    assert macro.swapped(rtl, data, tmp_path) == [rtl[0], tmp_path / "a.sv"]
    assert macro.macro_dbs(data, tmp_path) == [str(tmp_path / "M.db")] and macro.macro_cells(data) == ["M256X32"]
    f = fm.script_text([tmp_path / "a.sv"], "blk", ["/l/cells.db", "/m/M.db"], tmp_path / "n.v", None, tmp_path)
    assert f.count('"/m/M.db"') == 2  # (both containers)


# -- the step -----------------------------------------------------------------------------------------------------------

FAKE_LC = """import re, sys
from pathlib import Path
for out in re.findall(r'-output "([^"]+)"', Path(sys.argv[1]).read_text()):
    Path(out).write_text('db\\n')
print('Library Compiler')
"""


class MacroLLM:
    def __init__(self):
        self.stages = []
        self.plan = macro.CompilerPlan(usable=False, reason="no compiler")
        self.pins = PINS
        self.review = macro.Review(verdicts=[])

    async def __call__(self, stage, cfg, emit):
        from q3tui.llm.runtime import StageResult

        self.stages.append(stage.name)
        out = {"asic_macro_spec": SPEC, "asic_macro_pins": self.pins, "asic_macro_compiler": self.plan, "asic_macro_review": self.review}.get(stage.name)
        if out is None:
            from q3tui.flows.asic.lib.porter import PortPlan

            out = PortPlan()
        return StageResult("ok", out, 0.01, 1, "s")


@pytest.fixture
def llm(monkeypatch):
    from q3tui.llm import runtime

    fake = MacroLLM()
    monkeypatch.setattr(runtime, "run_stage", fake)
    return fake


@pytest.fixture
def proj(tmp_path):
    std = _pdk(tmp_path / "PDK")
    root = tmp_path / "p"
    (root / "src" / "rtl").mkdir(parents=True)
    (root / "src" / "rtl" / "m_buf_sram.sv").write_text(WRAPPER)
    (root / "src" / "rtl" / "blk.sv").write_text(TOP)
    (root / "src" / "rtl" / "filelist.f").write_text("src/rtl/m_buf_sram.sv\nsrc/rtl/blk.sv\n")
    (root / "schemas").mkdir()
    (root / "schemas" / "structured_spec.json").write_text(json.dumps({"metadata": {"top_module": "blk"}}))
    (root / "spec").mkdir()
    (root / "spec" / "spec.md").write_text("| **Clock** | `i_clk`, target frequency 200 MHz (5 ns period) |\n")
    (root / "fake_lc.py").write_text(FAKE_LC)
    (root / "q3tui.yaml").write_text(
        f"pipeline:\n  flow: asic\n  step_options:\n    asic_synth:\n      library: {std}\n"
        f"tools:\n  roles:\n    lib_compile:\n      cmd: \"{sys.executable} {root / 'fake_lc.py'} {{script}}\"\n      parse: generic\n")
    return Project.open(root)


async def test_the_step_maps_a_wrapper_to_macros(proj, llm):
    eng = Engine(proj)
    await eng.run(yes=True, stop="asic_macro")
    data = json.loads((proj.schemas_dir / "asic_macro.json").read_text())
    w = data["wrappers"]["m_buf_sram"]
    assert (w["how"], w["macro"], w["rows"], w["cols"], w["area_um2"]) == ("macros", "M256X32", 2, 1, 600.0), w
    assert w["asic_file"] == "build/syn/asic/macros/m_buf_sram.sv" and (proj.root / w["db"]).is_file()
    assert w["check"]["status"] == "n/a" and data["period_ns"] == 5.0 and data["corner"] == "tt0p9v25c"
    assert llm.stages.count("asic_macro_spec") == 1 and llm.stages.count("asic_macro_pins") == 1
    assert (proj.root / "src" / "rtl" / "m_buf_sram.sv").read_text() == WRAPPER  # (the RTL is never changed)
    step = eng.by_name["asic_synth"]
    assert step.synth_files(eng)[1] == proj.root / w["asic_file"] and step.macro_dbs(eng) == [str(proj.root / w["db"])]
    # an update: nothing changed — no LLM, the same macro
    llm.stages.clear()
    await Engine(Project.open(proj.root)).run(yes=True, only="asic_macro", regenerate=False)
    assert "asic_macro_spec" not in llm.stages and "asic_macro_pins" not in llm.stages


async def test_a_clock_too_fast_for_every_macro_keeps_flops(proj, llm):
    (proj.root / "spec" / "spec.md").write_text("| **Clock** | `i_clk`, target frequency 4000 MHz (0.25 ns period) |\n")
    await Engine(proj).run(yes=True, stop="asic_macro")
    w = json.loads((proj.schemas_dir / "asic_macro.json").read_text())["wrappers"]["m_buf_sram"]
    assert w["how"] == "flops" and not w["asic_file"] and "needs 0.5 ns" in w["why"]


async def test_no_wrapper_no_macro(proj, llm):
    (proj.root / "src" / "rtl" / "m_buf_sram.sv").rename(proj.root / "src" / "rtl" / "m_buf.sv")
    (proj.root / "src" / "rtl" / "m_buf.sv").write_text(WRAPPER.replace("m_buf_sram", "m_buf"))
    (proj.root / "src" / "rtl" / "blk.sv").write_text(TOP.replace("m_buf_sram", "m_buf"))
    (proj.root / "src" / "rtl" / "filelist.f").write_text("src/rtl/m_buf.sv\nsrc/rtl/blk.sv\n")
    await Engine(proj).run(yes=True, stop="asic_macro")
    assert json.loads((proj.schemas_dir / "asic_macro.json").read_text())["wrappers"] == {}
    assert "asic_macro_spec" not in llm.stages


FAKE_MC = """import sys
from pathlib import Path
sys.path.insert(0, {tests!r})
from test_asic_macro import _lib, _model
if {fail!r}:
    print('Error: no license')
    sys.exit(1)
Path('C512X32_tt0p9v25c.lib').write_text(_lib('C512X32', 512, 32, 200.0, 'tt0p9v25c'))
Path('C512X32_tt0p9v25c.v').write_text(_model('C512X32', 512, 32))
"""


def _with_compiler(proj, llm, fail: bool):
    kit = proj.root.parent / "PDK" / "MEMORY" / "kit" / "Compiler"
    kit.mkdir(parents=True)
    exe = kit / "mc2-eu"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (proj.root / "fake_mc.py").write_text(FAKE_MC.format(tests=str(Path(__file__).parent), fail=fail))
    y = proj.root / "q3tui.yaml"
    y.write_text(y.read_text() + f"    mem_compile:\n      cmd: \"{sys.executable} {proj.root / 'fake_mc.py'} {{config}}\"\n      parse: generic\n")
    llm.plan = macro.CompilerPlan(usable=True, reason="kit and license", cmd="mc2", config="512x32m4f\n",
                                  lib_glob="*_tt0p9v25c.lib", v_glob="*_tt0p9v25c.v")
    return Project.open(proj.root)


async def test_a_compiled_macro_wins(proj, llm):
    p = _with_compiler(proj, llm, fail=False)
    await Engine(p).run(yes=True, stop="asic_macro")
    data = json.loads((p.schemas_dir / "asic_macro.json").read_text())
    w = data["wrappers"]["m_buf_sram"]
    assert (w["how"], w["macro"], w["rows"], w["cols"]) == ("compiled", "C512X32", 1, 1), w
    assert data["compiler"]["usable"] and "asic_macro_compiler" in llm.stages


async def test_a_failed_compiler_falls_back_to_the_generated_macros(proj, llm):
    p = _with_compiler(proj, llm, fail=True)
    await Engine(p).run(yes=True, stop="asic_macro")
    w = json.loads((p.schemas_dir / "asic_macro.json").read_text())["wrappers"]["m_buf_sram"]
    assert (w["how"], w["macro"], w["rows"]) == ("macros", "M256X32", 2), w


async def test_the_macros_tab(proj, llm):
    from q3tui.flows.asic import panels
    from q3tui.tui.app import Q3TUIApp

    await Engine(proj).run(yes=True, stop="asic_macro")
    app = Q3TUIApp(Project.open(proj.root))
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        assert [t.id for t in panels._tabs_for("asic.asic_macro")] == ["macros"]
        (row,) = panels._macro_rows(app)
        assert row[0] == "m_buf_sram" and str(row[2]) == "macros" and row[3] == "M256X32" and row[4] == "2 x 1" and str(row[6]) == "n/a"
        text = panels._macro_detail(app, "m_buf_sram")
        assert "512 x 32" in text and "2 x 1 `M256X32`" in text and "build/syn/asic/macros/m_buf_sram.sv" in text


async def test_no_pdk_fails_instead_of_passing_flops(proj, llm):
    y = proj.root / "q3tui.yaml"
    y.write_text(y.read_text().replace("library:", "other:"))
    eng = Engine(Project.open(proj.root))
    await eng.run(yes=True, stop="asic_macro")
    assert eng.state.steps["asic_macro"].status == "failed" and "no PDK folder" in (eng.state.steps["asic_macro"].error or "")


def test_the_pdk_folder_of_a_deep_library(tmp_path):
    deep = tmp_path / "PDK" / "STD_CELL" / "kit" / "a" / "b" / "c" / "d" / "e" / "f" / "g" / "h" / "i"
    deep.mkdir(parents=True)
    (tmp_path / "PDK" / "MEMORY").mkdir()
    assert macro.pdk_root(str(deep / "cells_tt0p9v25c.db")) == tmp_path / "PDK"


async def test_a_large_memory_left_as_flops_is_a_question(proj, llm, monkeypatch):
    monkeypatch.setattr(macro, "REVIEW_BYTES", 1024)  # (the 512 x 32 test wrapper is 2 KB)
    llm.pins = PINS.model_copy(update={"ties": {"BIST": "low"}})  # (the pin check rejects every family: "not a Verilog constant")
    llm.review = macro.Review(verdicts=[macro.Verdict(wrapper="m_buf_sram", kind="check_wrong", macro="M256X32",
                                                      explanation="`low` is the documented normal level of BIST.")])
    eng = Engine(proj)
    await eng.run(yes=True, stop="asic_macro")
    data = json.loads((proj.schemas_dir / "asic_macro.json").read_text())
    assert data["wrappers"]["m_buf_sram"]["how"] == "flops" and "asic_macro_review" in llm.stages
    step = eng.by_name["asic_macro"]
    (q,) = step.questions_list(eng)
    assert q.blocking and q.options[0].label == "use M256X32 anyway" and "keep flip-flops" in [o.label for o in q.options]
    assert data["asks"][q.id]["macro"] == "M256X32" and data["asks"][q.id]["pin_key"]
    # the answer: the check is wrong — the macro is used, no question is left, the review is not asked again
    assert step.answer(eng, q.id, "use M256X32 anyway")
    llm.stages.clear()
    llm.pins = PINS  # (would pass now: shows the kept map is reused, not asked again)
    eng2 = Engine(Project.open(proj.root))
    await eng2.run(yes=True, only="asic_macro")
    w = json.loads((proj.schemas_dir / "asic_macro.json").read_text())["wrappers"]["m_buf_sram"]
    assert (w["how"], w["macro"]) == ("macros", "M256X32") and "overridden" in w["why"]
    assert "asic_macro_pins" not in llm.stages and "asic_macro_review" not in llm.stages
    assert eng2.by_name["asic_macro"].open_questions(eng2) == 0


async def test_intended_flops_ask_nothing_and_are_not_judged_again(proj, llm, monkeypatch):
    monkeypatch.setattr(macro, "REVIEW_BYTES", 1024)
    llm.pins = PINS.model_copy(update={"ties": {"BIST": "low"}})
    llm.review = macro.Review(verdicts=[macro.Verdict(wrapper="m_buf_sram", kind="intended", explanation="no macro has this.")])
    eng = Engine(proj)
    await eng.run(yes=True, stop="asic_macro")
    assert eng.by_name["asic_macro"].questions_list(eng) == [] and "asic_macro_review" in llm.stages
    w = json.loads((proj.schemas_dir / "asic_macro.json").read_text())["wrappers"]["m_buf_sram"]
    assert w["review"]["kind"] == "intended"
    llm.stages.clear()
    eng = Engine(Project.open(proj.root))
    await eng.run(yes=True, only="asic_macro", regenerate=True)
    assert "asic_macro_review" not in llm.stages


async def test_keep_flops_settles_a_mismatch(proj, llm, monkeypatch):
    monkeypatch.setattr(macro, "REVIEW_BYTES", 1024)
    llm.pins = PINS.model_copy(update={"ties": {"BIST": "low"}})
    llm.review = macro.Review(verdicts=[macro.Verdict(wrapper="m_buf_sram", kind="mismatch", explanation="x", request="register the read")])
    eng = Engine(proj)
    await eng.run(yes=True, stop="asic_macro")
    (q,) = eng.by_name["asic_macro"].questions_list(eng)
    assert [o.label for o in q.options] == ["keep flip-flops", "change the design"] and q.default_assumption == "keep flip-flops"
    eng.by_name["asic_macro"].answer(eng, q.id, "keep flip-flops")
    llm.stages.clear()
    eng = Engine(Project.open(proj.root))
    await eng.run(yes=True, only="asic_macro")
    w = json.loads((proj.schemas_dir / "asic_macro.json").read_text())["wrappers"]["m_buf_sram"]
    assert w["how"] == "flops" and w["why"] == "flip-flops: your answer" and "asic_macro_review" not in llm.stages
    assert eng.by_name["asic_macro"].open_questions(eng) == 0


async def test_change_the_design_goes_to_the_spec_once(proj, llm, monkeypatch):
    from q3tui import flows

    monkeypatch.setattr(macro, "REVIEW_BYTES", 1024)
    llm.pins = PINS.model_copy(update={"ties": {"BIST": "low"}})
    llm.review = macro.Review(verdicts=[macro.Verdict(wrapper="m_buf_sram", kind="mismatch", explanation="x", request="register the read")])
    eng = Engine(proj)
    await eng.run(yes=True, stop="asic_macro")
    (q,) = eng.by_name["asic_macro"].questions_list(eng)
    eng.by_name["asic_macro"].answer(eng, q.id, "change the design")
    e2 = Engine(Project.open(proj.root))
    await e2.run(yes=True, only="asic_macro")
    e2.by_name["asic_macro"]._send_changes(e2, data_asks := json.loads((proj.schemas_dir / "asic_macro.json").read_text())["asks"], {q.id: "change"}, {q.id: "change the design"})
    assert data_asks[q.id]["sent"]  # (sent once: a later run does not send it again)
    (req,) = Engine(Project.open(proj.root), flow=flows.load_flow("rtl", proj.root)).state.feedback["spec"]
    assert "m_buf_sram" in req and "register the read" in req
    data = json.loads((proj.schemas_dir / "asic_macro.json").read_text())
    assert data["asks"][q.id]["sent"]["step"] == "spec"
