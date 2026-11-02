"""Sanity step `setup`: the CDC / RDC analysis environment (resets, black boxes, quasi-static signals, constants, reset synchronizers), decided by a
read-only LLM stage from the spec and the RTL, checked by code (names) and by an elaboration-only run of the tool, reviewed at the gate
(lib/setup.py; docs/spec/sanity-flow.md "The setup")."""

from __future__ import annotations

import json
from pathlib import Path

from q3tui.flows import skill_sections
from q3tui.flows.sanity.lib import script, setup as setupmod
from q3tui.flows.sanity.lib.base import SanityStep
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext

HERE = Path(__file__).parent
SYSTEM = skill_sections(HERE / "md" / "skill.md")["SYSTEM"]
FIX_ROUNDS = 2


class Step(SanityStep):
    name = "setup"
    title = "CDC / RDC setup"
    deps = ("sdc",)
    role = "cdc"  # (the dry run elaborates with the `cdc` tool role)
    checks_version = 1  # (1: the black boxes' pins are constrained on their clock)
    tool_roles = ()

    def inputs(self, engine) -> list[Path]:
        return [self.filelist(engine), *self.rtl_files(engine), *self.sdc_files(engine), *engine.project.spec_documents()]

    def outputs(self, engine) -> list[Path]:
        return [p for p in (self.artifact(engine, setupmod.SETUP_JSON), self.report_file(engine)) if p.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return self.outputs(engine)

    def report_file(self, engine) -> Path:
        return engine.project.reports_dir / "sanity_setup.md"

    def missing_input(self, engine) -> str | None:
        if why := self.missing_rtl(engine):
            return why
        if self.sdc_top(engine) is None:
            return "the SDC is needed first (step sdc: constraints/sdc/sdc.tcl)"
        return None

    # -- the prompt -------------------------------------------------------------------------------------------------------------------------------

    def _facts(self, engine, top: str, ports, modules: list[str]) -> str:
        from q3tui.core.project import read_json
        from q3tui.tui import failures

        project = engine.project
        sdcj = read_json(project.sdc_dir / "sdc.json", {}) or {}
        lines = [f"## Facts (code)", f"Top `{top}`; RTL modules (src/rtl/<module>.sv): {', '.join(modules)}."]
        if ports:
            lines.append("Top ports: " + ", ".join(f"{d} {n}" for d, n in ports))
        lines.append("SDC (" + ", ".join(f"`{project.rel(f)}`" for f in self.sdc_files(engine)) + "): clocks "
                     + (", ".join(f"{c.get('name')} ({c.get('freq_mhz') or c.get('period_ns')})" for c in sdcj.get("clocks") or []) or "see the files")
                     + "; resets " + (", ".join(map(str, sdcj.get("resets") or [])) or "none listed"))
        arr = setupmod.arrays(self.rtl_files(engine))
        if arr:
            lines.append("Unpacked arrays per module (candidates for black boxes when they are memories with no reset):")
            lines += [f"- {m}: {', '.join(a)}" for m, a in arr.items()]
        try:
            from q3tui.eda import tools as toolmod

            cmd = toolmod.load_tools(project.cfg, project.root).roles.get("rdc") or toolmod.load_tools(project.cfg, project.root).roles.get("cdc")
            peaks = failures.memory_peaks(project, cmd.cmd) if cmd else []
        except Exception:  # noqa: BLE001 - no tools file: no memory facts
            peaks = []
        if peaks:
            lines += [f"Memory the tool needed in earlier runs (this machine: {failures.machine()}):", *peaks]
        lines.append("The spec: " + ", ".join(f"`{project.rel(f)}`" for f in project.spec_documents()))
        return "\n".join(lines)

    # -- the dry run --------------------------------------------------------------------------------------------------------------------------------

    def _dry_run(self, engine, top: str, plan: dict) -> list[str] | None:
        """Elaborate with the setup's commands, no check (the `cdc` role): the setup's own errors; None when the tool cannot run here."""
        from q3tui.eda import tools as toolmod

        project = engine.project
        try:
            tools = toolmod.load_tools(project.cfg, project.root)
            if "cdc" not in tools.roles or not toolmod.available(tools, "cdc"):
                return None
        except Exception:  # noqa: BLE001
            return None
        from q3tui.flows.sanity.lib import vcstatic

        work = self.workdir(engine)
        vcstatic.clear_stale_lock(work)
        f = work / "setup_dry.tcl"
        resets = setupmod.reset_lines(plan) or ""
        f.write_text("\n".join([
            f"cd {work}", "set_app_var enable_cdc true", script.blackbox_lines(setupmod.blackbox_modules(plan)).rstrip(),
            f'analyze -format sverilog -vcs "-f {script.absolute_filelist(self.filelist(engine), project.root, work)}"', f"elaborate {top}",
            f"read_sdc {self.sdc_top(engine)}", resets.rstrip(), setupmod.tcl(plan, "rdc").rstrip(), "quit", ""]))
        res = toolmod.run_role(tools, "cdc", work, {"script": f, "top": top, "filelist": self.filelist(engine), "files": self.rtl_files(engine),
                                                    "workdir": work}, log_name="setup_dry.log")
        if toolmod.broken(res, "cdc") and not Path(res.log_path or "").is_file():
            return None
        log = Path(res.log_path).read_text(errors="replace") if res.log_path else ""
        return [x for x in setupmod.tool_errors(log) if f.name in x or "TCL_COMMAND_INVALID" in x]

    def clocks(self, engine) -> list[str]:
        """The SDC's clock names (sdc.json, else the `create_clock -name` of the SDC files)."""
        import re

        from q3tui.core.project import read_json

        sdcj = read_json(engine.project.sdc_dir / "sdc.json", {}) or {}
        names = [str(c.get("name")) for c in sdcj.get("clocks") or [] if c.get("name")]
        if not names:
            for f in self.sdc_files(engine):
                names += re.findall(r"create_clock\b[^\n]*?-name\s+\{?(\w+)", f.read_text(errors="replace"))
        return list(dict.fromkeys(names))

    def complete(self, engine, plan: setupmod.SanitySetup, des, top: str, clocks: list[str]) -> dict:
        """The setup as data with what code adds: the SDC clocks, the black boxes' instances and data pins (yours, options.blackbox, too)."""
        data = plan.model_dump()
        yours = [m for st in ("cdc", "rdc") if st in engine.by_name for m in setupmod.blackbox_modules(None, engine.by_name[st].options.get("blackbox"))]
        data["clocks"] = clocks
        data["blackbox_pins"] = setupmod.blackbox_pins(des, top, list(dict.fromkeys([b.module for b in plan.blackbox] + yours)))
        return data

    # -- run ----------------------------------------------------------------------------------------------------------------------------------------

    async def run(self, ctx: StepContext) -> None:
        import anyio

        engine, project = ctx.engine, ctx.project
        top = self.top(engine)
        modules = sorted(f.stem for f in self.rtl_files(engine))
        des = await anyio.to_thread.run_sync(lambda: setupmod.design(self.filelist(engine), project.root, top))
        ports = setupmod.top_ports(self.filelist(engine), project.root, top, des)
        clocks = self.clocks(engine)
        prev = self.read(engine, setupmod.SETUP_JSON, None)
        parts = ["# Task: set up the CDC / RDC analysis", "", self._facts(engine, top, ports, modules)]
        if prev and not ctx.regenerate:
            parts += ["", "## The earlier setup (the starting point)", "```json", json.dumps(prev, indent=1), "```"]
        if ctx.feedback:
            parts += ["", "## Change requests", *(f"- {f}" for f in ctx.feedback)]
        stage = Stage(name="sanity_setup", system_prompt=SYSTEM, prompt="\n".join(parts), cwd=project.root, builtin_tools=["Read", "Grep", "Glob"],
                      output_model=setupmod.SanitySetup, deny_dirs=[project.src_dir / "tb", project.src_dir / "sva", project.tb_dir, project.model_dir])
        res = await ctx.llm(stage)
        plan: setupmod.SanitySetup = res.output
        for i in range(FIX_ROUNDS + 1):
            wrong = setupmod.problems(plan, set(modules), ports, clocks)
            if not wrong:
                errs = await anyio.to_thread.run_sync(lambda: self._dry_run(engine, top, self.complete(engine, plan, des, top, clocks)))
                if errs is None:
                    ctx.emit("log", message="setup: the tool is not here: the names were checked against the RTL only (no dry run)")
                elif errs:
                    wrong = [f"the tool: {e}" for e in errs]
            if not wrong:
                break
            if i == FIX_ROUNDS or not res.session_id:
                ctx.emit("warning", message="setup: still wrong after the fix rounds, left out: " + "; ".join(wrong[:5]))
                plan = _drop_wrong(plan, wrong)
                break
            ctx.emit("log", message=f"setup: {len(wrong)} problem(s): fixing — " + "; ".join(wrong[:3]))
            res = await ctx.llm(Stage(name="sanity_setup", system_prompt=SYSTEM, cwd=project.root, builtin_tools=["Read", "Grep", "Glob"],
                                      output_model=setupmod.SanitySetup, deny_dirs=list(stage.deny_dirs), resume=res.session_id,
                                      prompt="# Task: fix the setup\nThese are wrong (code and the tool checked them):\n" + "\n".join(f"- {w}" for w in wrong)
                                             + "\nUse the real names (the RTL; hierarchical names from the top as u_inst.signal). Answer with the whole setup again."))
            plan = res.output
        data = self.complete(engine, plan, des, top, clocks)
        ctx.unchanged = bool(prev) and prev == data
        self.write(engine, setupmod.SETUP_JSON, data)
        self.report_file(engine).parent.mkdir(parents=True, exist_ok=True)
        self.report_file(engine).write_text(setupmod.markdown(data) + "\n")
        ctx.emit("log", message=f"setup: {len(plan.resets)} reset(s), {len(plan.blackbox)} black box(es), {len(plan.quasi_static)} quasi-static, "
                                f"{len(plan.constants)} constant(s), {len(plan.reset_synchronizers)} reset synchronizer(s); {project.rel(self.report_file(engine))}")


def _drop_wrong(plan: setupmod.SanitySetup, wrong: list[str]) -> setupmod.SanitySetup:
    """What stayed wrong after the fix rounds is left out (never a setup the tool rejects): the names the messages mention."""
    text = " ".join(wrong)
    return plan.model_copy(update={
        "resets": [r for r in plan.resets if f"`{r.port}`" not in text and r.port not in text],
        "blackbox": [b for b in plan.blackbox if f"`{b.module}`" not in text],
        "quasi_static": [s for s in plan.quasi_static if s.signal not in text and s.signal.replace(".", "/") not in text],
        "constants": [c for c in plan.constants if f"`{c.port}`" not in text and c.port not in text],
        "reset_synchronizers": [s for s in plan.reset_synchronizers if f"`{s.module}`" not in text],
    })
