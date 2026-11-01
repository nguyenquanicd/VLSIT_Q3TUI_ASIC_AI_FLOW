"""Running steps: tools by role, log readers, step.py and the built-in runner, addons, and the LLM runtime with a
fake LLM (spec/tools.md, spec/extensibility.md, spec/llm-runtime.md). No live LLM."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from q3tui.config import ConfigLayers
from q3tui.engine import EngineError
from q3tui.engine.events import read_events
from q3tui.llm import runtime as llm
from q3tui.llm.runtime import Access
from q3tui.runtime.session import open_project
from q3tui.tools.readers import read_log
from q3tui.tools.roles import ToolEnv
from q3tui.tools.run import ToolBroken, ToolError, ToolRunner, render


def write(path: Path, text: str, mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode:
        path.chmod(mode)
    return path


# -- tools --------------------------------------------------------------------------------------------


def test_render():
    assert render("vcs -top {top} {files} -o {workdir}/simv", {"top": "t", "files": ["a.sv", "b.sv"], "workdir": "/w"}) \
        == ["vcs", "-top", "t", "a.sv", "b.sv", "-o", "/w/simv"]
    with pytest.raises(ToolError, match=r"needs \{top\} \(available: workdir\)"):
        render("vcs {top}", {"workdir": "/w"})


def runner(tmp: Path, roles: str) -> ToolRunner:
    cfg_file = write(tmp / "cfg.yaml", f"tools:\n  timeout_s: 2\n  roles:\n{roles}")
    cfg = ConfigLayers(None, cfg_file)
    return ToolRunner(cfg, ToolEnv(cfg.config), tmp, lambda step: tmp / "work" / step)


async def test_tool_result_and_log(tmp_path):
    tool = write(tmp_path / "lint.sh", "#!/bin/sh\necho \"Warning: unused $1\"\necho 'Error: bad thing'\nexit 1\n", 0o755)
    r = runner(tmp_path, f"    lint: {{cmd: '{tool} {{top}}', parse: generic, ok_returncodes: [0, 1]}}\n")
    res = await r.run("style", "lint", vars={"top": "fifo"})
    assert (res.ok, res.returncode, res.errors, res.warnings) == (False, 1, 1, 1)
    assert res.log == tmp_path / "work/style/lint.log" and "unused fifo" in res.log.read_text()


async def test_broken_tool_and_timeouts(tmp_path):
    bad = write(tmp_path / "bad.sh", "#!/bin/sh\necho 'tool failed'\nexit 2\n", 0o755)
    slow = write(tmp_path / "slow.sh", "#!/bin/sh\nsleep 5\n", 0o755)
    r = runner(tmp_path, f"    bad: {{cmd: '{bad}'}}\n    sim: {{cmd: '{slow}', timeout_s: 1}}\n")
    with pytest.raises(ToolBroken, match="exited with 2"):
        await r.run("s", "bad")
    with pytest.raises(ToolBroken, match="timed out"):
        await r.run("s", "sim")
    res = await r.run("s", "sim", timeout="result", log="run_t1.log")
    assert res.timed_out and not res.ok and res.log.name == "run_t1.log"


async def test_progress_of_a_long_tool(tmp_path, monkeypatch):
    from q3tui.tools import run as run_mod

    monkeypatch.setattr(run_mod, "PROGRESS_S", 0.2)
    slow = write(tmp_path / "slow.sh", "#!/bin/sh\necho 'pass 1 of 3'\nsleep 0.7\n", 0o755)
    r = runner(tmp_path, f"    synth: {{cmd: '{slow}'}}\n")
    lines = []
    await r.run("s", "synth", progress=lines.append)
    assert lines and lines[0] == "synth: running 0 s — pass 1 of 3"


async def test_missing_tool(tmp_path):
    r = runner(tmp_path, "    sim: {cmd: 'no-such-simulator {top}'}\n")
    res = await r.run("s", "sim", required=False)
    assert res.na and not res.ok
    with pytest.raises(ToolError, match="not found"):
        await r.run("s", "sim")


async def test_stop_kills_the_tool(tmp_path):
    slow = write(tmp_path / "slow.sh", f"#!/bin/sh\nsleep 30\ntouch {tmp_path}/finished\n", 0o755)
    r = runner(tmp_path, f"    sim: {{cmd: '{slow}', timeout_s: 60}}\n")
    task = asyncio.ensure_future(r.run("s", "sim"))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (tmp_path / "finished").exists()


def test_readers():
    vcs = 'Error-[SE] Syntax error\n  Following verilog source has syntax error :\n  "rtl/foo.sv", 12: token is \'end\'\n'
    d = read_log("vcs", vcs)[0]
    assert (d.severity, d.file, d.line, d.code) == ("error", "rtl/foo.sv", 12, "SE")
    assert [x.severity for x in read_log("generic", "ERROR x\nwarning y\nfine")] == ["error", "warning"]
    assert [x.severity for x in read_log({"error": ["^E-"]}, "E-1\nerror here\nWarning w")] == ["error", "warning"]
    with pytest.raises(ValueError, match="unknown log reader"):
        read_log("nope", "")


# -- what an LLM task may read --------------------------------------------------------------------------


def test_access(tmp_path):
    root = tmp_path
    write(root / "spec/spec.md", "s")
    write(root / "src/rtl/a.sv", "a")
    write(root / "src/tb/t.sv", "t")
    acc = Access(root, [root / "spec/spec.md", root / "src/rtl"], [root / "src/rtl"], root / ".q3tui/state")
    assert acc.check("Read", {"file_path": "spec/spec.md"}) is None
    assert acc.check("Read", {"file_path": "src/tb/t.sv"}) == "`src/tb/t.sv` is not an input of this step"
    assert "may not" not in (acc.check("Write", {"file_path": "src/rtl/b.sv"}) or "")
    assert acc.check("Write", {"file_path": "spec/spec.md"}).startswith("`spec/spec.md` is not an output")
    assert "Q3TUI's own state" in acc.check("Read", {"file_path": ".q3tui/state/pipeline.json"})
    assert acc.check("Grep", {"pattern": "x"}).startswith("give Grep a `path`")
    assert acc.glob("**/*.sv") == "src/rtl/a.sv"


# -- a project with real step code and a fake LLM ----------------------------------------------------------


class FakeLLM:
    """Replaces `claude_agent_sdk.query`: each call takes the next reply; it records the prompts and options."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, *, prompt, options):
        self.calls.append((prompt, options))
        reply = self.replies.pop(0)

        async def gen():
            if callable(reply):
                for m in reply(prompt, options):
                    yield m
                return
            text, structured = reply
            yield AssistantMessage([TextBlock(text)], "claude-test")
            yield ResultMessage("success", 1, 1, False, 1, f"sess-{len(self.calls)}", total_cost_usd=0.01 * len(self.calls),
                                result=text, structured_output=structured, uuid=f"u{len(self.calls)}")

        return gen()


FLOW = "---\nname: f\ndescription: d\nversion: 1.0.0\nstages: [s]\n---\n"
STAGE = ("---\nname: s\ndescription: d\nversion: 1.0.0\nparams:\n  lang: {type: str, default: SV}\nsteps: [{steps}]\n---\n"
         "<!-- SYSTEM PROMPT -->\nYou design {{lang}} hardware.\n<!-- /SYSTEM PROMPT -->\n")


def home_with(tmp: Path, steps: dict[str, tuple[str, str]], files: dict[str, str] | None = None) -> Path:
    home = tmp / "home"
    write(home / "flows/f/FLOW.md", FLOW)
    write(home / "stages/s/STAGE.md", STAGE.replace("{steps}", ", ".join(steps)))
    for name, (front, body) in steps.items():
        write(home / f"steps/{name}/STEP.md", f"---\nname: {name}\ndescription: d\nversion: 1.0.0\n{front}---\n{body}")
    for rel, text in (files or {}).items():
        write(home / rel, text)
    return home


async def test_builtin_runner_with_a_fake_llm(tmp_path, monkeypatch):
    home = home_with(tmp_path, {"plan": (
        ("params:\n  depth: {type: int, default: 4}\noutputs:\n  - {artifact: plan, path: out/plan.json}\n"
        "tasks:\n  - {name: draft, output: plan.schema.json, to: plan}\n"),
        "<!-- draft -->\nPlan a FIFO of depth {{depth}}.\n<!-- /draft -->\n")},
        {"steps/plan/plan.schema.json": json.dumps({"type": "object", "required": ["depth"],
                                                     "properties": {"depth": {"type": "integer"}}})})
    fake = FakeLLM([("here", {"size": 1}), ("fixed", {"depth": 4})])
    monkeypatch.setattr(llm, "query", fake)
    opened = open_project(tmp_path / "proj", home=home, flow="f")
    assert not opened.problems
    res = await opened.ops.run()
    assert res[0].outcome == "complete", opened.engine.status("plan").reason
    assert json.loads((opened.project.root / "out/plan.json").read_text()) == {"depth": 4}
    prompt, options = fake.calls[0]
    assert "Plan a FIFO of depth 4." in prompt and prompt.startswith("[Q3TUI] This task may read")
    assert options.system_prompt == "You design SV hardware." and options.resume is None
    assert "does not match its schema" in fake.calls[1][0] and fake.calls[1][1].resume == "sess-1"
    assert opened.ops.cost()["steps"]["plan"] == pytest.approx(0.02)
    kinds = [e["kind"] for e in read_events(opened.project.events_file)]
    assert {"task_started", "task_text", "task_finished", "sdk"} <= set(kinds)


async def test_session_kept_across_runs_and_new_on_regenerate(tmp_path, monkeypatch):
    home = home_with(tmp_path, {"w": ("outputs:\n  - {artifact: w, path: out/w.md}\ntasks:\n  - {name: t, to: w}\n",
                                      "<!-- t -->\nWrite.\n<!-- /t -->\n")})
    fake = FakeLLM([("one", None), ("two", None), ("three", None)])
    monkeypatch.setattr(llm, "query", fake)
    opened = open_project(tmp_path / "proj", home=home, flow="f")
    await opened.ops.run()
    opened.ops.request_change("w", "shorter")
    await opened.ops.run()
    assert fake.calls[1][1].resume == "sess-1"
    await opened.ops.run(regenerate=["w"])
    assert fake.calls[2][1].resume is None
    assert (opened.project.root / "out/w.md").read_text() == "three"


async def test_step_py_with_tool_and_mcp(tmp_path, monkeypatch):
    sim = write(tmp_path / "sim.sh", "#!/bin/sh\necho \"running $1\"\nexit 0\n", 0o755)
    step_py = '''
from q3tui.step import mcp_tool

class Step:
    async def run(self, ctx):
        r = await ctx.tool("sim", top=ctx.params["top"])
        text = await ctx.task("triage", log=r.log.read_text())
        ctx.outputs["report"].write_text(text)
        if "bad" in text:
            ctx.handback("rtl_fix", "top", "t1", text)

    def check_has_report(self, ctx):
        return ctx.outputs["report"].exists() or "no report"

    @mcp_tool("count", "How many", {"n": int})
    async def count(self, ctx, args):
        return str(args["n"] * 2)
'''
    home = home_with(tmp_path, {
        "rtl": ("outputs:\n  - {artifact: rtl, path: out/rtl.sv}\nreceives: [rtl_fix]\ntasks:\n  - {name: w, to: rtl}\n",
                "<!-- w -->\nWrite RTL.\n<!-- /w -->\n"),
        "smoke": (("params:\n  top: {type: str, default: fifo}\ninputs:\n  - {artifact: rtl}\n"
                  "outputs:\n  - {artifact: report, path: out/report.md}\ntools:\n  - {role: sim}\nhandback: [rtl_fix]\n"
                  "mcp_tools: [count, tools_available]\npass:\n  - {check: \"code has_report\"}\n"
                  "  - {check: \"tool sim ok and errors == 0\"}\ntasks:\n  - {name: triage}\n"),
                  "<!-- triage -->\nTriage:\n{{log}}\n<!-- /triage -->\n")},
        {"steps/smoke/step.py": step_py})
    write(home / "config.yaml", f"tools:\n  roles:\n    sim: {{cmd: '{sim} {{top}}'}}\n")
    fake = FakeLLM([("module fifo; endmodule", None), ("bad: x stuck", None), ("module fifo; fixed", None),
                    ("all good", None)])
    monkeypatch.setattr(llm, "query", fake)
    opened = open_project(tmp_path / "proj", home=home, flow="f")
    assert not opened.problems, opened.problems
    res = await opened.ops.run()
    assert res[0].outcome == "complete", [opened.engine.status(s).reason for s in ("rtl", "smoke")]
    assert "running fifo" in fake.calls[1][0]
    servers = fake.calls[1][1].mcp_servers
    assert "mcp__q3tui__count" in fake.calls[1][1].allowed_tools and "q3tui" in servers
    started = [e for e in read_events(opened.project.events_file) if e["kind"] == "step_started" and e["step"] == "rtl"]
    assert started[1]["changes"]["requests"] == ["[fix] bad: x stuck"]  # the problem reached rtl as a change request
    assert fake.calls[2][0].startswith("[Q3TUI] What changed since the last run:\n"
                                       "- request (fix, unit top): bad: x stuck\n")
    assert (opened.project.root / "out/report.md").read_text() == "all good"


async def test_project_step_code_needs_allow(tmp_path, monkeypatch):
    home = home_with(tmp_path, {"a": ("outputs:\n  - {artifact: a, path: out/a.txt}\n", "")})
    proj = tmp_path / "proj"
    step_py = write(proj / ".q3tui/steps/a/step.py",
                    "class Step:\n    async def run(self, ctx):\n        ctx.outputs['a'].parent.mkdir(exist_ok=True)\n        ctx.outputs['a'].write_text('x')\n")
    write(proj / ".q3tui/steps/a/STEP.md", (home / "steps/a/STEP.md").read_text())
    opened = open_project(proj, home=home, flow="f")
    await opened.ops.run()
    assert "code not approved" in opened.engine.status("a").reason
    opened.ops.allow("code", step_py.read_bytes())
    await opened.ops.run()
    assert opened.engine.status("a").display == "done"


async def test_addons(tmp_path):
    addon = '''
def register(api):
    @api.action("sdc_set", "Change one value", params={"key": "the name", "value": "the value"})
    def sdc_set(ops, key, value):
        return f"SDC: {key} = {value}"

    api.parser("my_tool", lambda text: [])
    api.importer("import_rtl", lambda ops, files: [f for f in files if f.suffix == ".sv"], accepts=["*.sv", "*.v"])
'''
    home = home_with(tmp_path, {"a": ("outputs:\n  - {artifact: a, path: out/a.txt}\n", "")},
                     {"steps/a/addon.py": addon})
    opened = open_project(tmp_path / "proj", home=home, flow="f")
    assert sorted(a.name for a in opened.ops.actions()) == ["import_rtl", "sdc_set"]
    assert opened.ops.call_action("sdc_set", key="clk", value="2") == "SDC: clk = 2"
    with pytest.raises(EngineError):
        opened.ops.call_action("sdc_set", nope="1")
    write(tmp_path / "in/a.sv", "")
    write(tmp_path / "in/notes.txt", "")
    table = opened.ops.import_files([tmp_path / "in"])
    assert table == {str(tmp_path / "in/a.sv"): "a", str(tmp_path / "in/notes.txt"): None}
    assert "my_tool" in opened.addons.readers


def test_addon_name_clash(tmp_path):
    addon = "def register(api):\n    @api.action('approve', 'no')\n    def f(ops):\n        return ''\n"
    home = home_with(tmp_path, {"a": ("outputs:\n  - {artifact: a, path: out/a.txt}\n", "")},
                     {"steps/a/addon.py": addon})
    opened = open_project(tmp_path / "proj", home=home, flow="f")
    assert opened.engine is None
    assert [p.message for p in opened.problems] == ["action `approve` takes the name of an Ops action"]


async def test_checkpoint_after_a_stop(tmp_path, monkeypatch):
    step_py = '''
import asyncio

class Step:
    async def run(self, ctx):
        first = await ctx.task("a")
        await ctx.task("b")
        ctx.outputs["o"].parent.mkdir(parents=True, exist_ok=True)
        ctx.outputs["o"].write_text(first)
'''
    home = home_with(tmp_path, {"o": ("outputs:\n  - {artifact: o, path: out/o.md}\ntasks:\n  - {name: a}\n  - {name: b}\n",
                                      "<!-- a -->\nA\n<!-- /a -->\n<!-- b -->\nB\n<!-- /b -->\n")},
                     {"steps/o/step.py": step_py})
    gate = asyncio.Event()

    def hang(prompt, options):
        gate.set()
        raise asyncio.CancelledError

    fake = FakeLLM([("from a", None), hang, ("from b", None)])
    monkeypatch.setattr(llm, "query", fake)
    opened = open_project(tmp_path / "proj", home=home, flow="f")
    run = asyncio.ensure_future(opened.ops.run())
    await gate.wait()
    opened.ops.stop()
    await run
    assert opened.engine.status("o").display == "pending"
    session = json.loads((opened.project.session_dir("o") / "session.json").read_text())
    assert session["rewind_to"] is None or "rewind_to" in session
    await opened.ops.run()
    assert len(fake.calls) == 3  # task a was kept: only b was asked again
    assert (opened.project.root / "out/o.md").read_text() == "from a"
    assert not opened.project.cache_dir("o").exists()


def test_tool_use_block_marks_a_write():
    assert ToolUseBlock("1", "Write", {}).name in llm.WRITE_TOOLS


@pytest.mark.skipif(shutil.which("q3-hdl") is None, reason="the design reader q3-hdl (a tool of the flow) is not installed")
async def test_the_design_reader_is_a_tool_by_role(tmp_path):
    """Reading the design is the flow's tool `hdl` (q3-hdl), run by role like any other tool: not part of Q3TUI."""
    step_py = '''
import json
import shutil

class Step:
    async def run(self, ctx):
        out = ctx.outputs["ports"]
        r = await ctx.tool("hdl", command="parse", files=[str(p) for p in ctx.inputs["rtl"]], top="top",
                           out=str(out.with_suffix(".design.json")))
        design = json.loads(out.with_suffix(".design.json").read_text())
        out.write_text(json.dumps([p["name"] for p in design["modules"]["top"]["ports"]]))
'''
    home = home_with(tmp_path, {"ports": (
        ("inputs:\n  - {artifact: rtl, path: src/top.sv}\noutputs:\n  - {artifact: ports, path: out/ports.json}\n"
         "tools:\n  - {role: hdl}\npass:\n  - {check: \"tool hdl ok and errors == 0\"}\n"), "")},
        {"steps/ports/step.py": step_py})
    write(home / "config.yaml", "tools:\n  roles:\n    hdl: {cmd: 'q3-hdl {command} {files} --top {top} -o {out}'}\n")
    write(tmp_path / "proj/src/top.sv", "module top(input logic clk, input logic rst_n, output logic q);\n"
          "  always_ff @(posedge clk or negedge rst_n) q <= !rst_n ? 1'b0 : ~q;\nendmodule\n")
    opened = open_project(tmp_path / "proj", home=home, flow="f")
    assert not opened.problems, opened.problems
    res = await opened.ops.run()
    assert res[0].outcome == "complete", opened.engine.status("ports").reason
    assert json.loads((opened.project.root / "out/ports.json").read_text()) == ["clk", "rst_n", "q"]
