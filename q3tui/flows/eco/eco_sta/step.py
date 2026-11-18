"""ECO step `eco_sta`: STA of the Post NETLIST with PrimeTime (tool role `eco_sta`): setup and hold paths, all violators, the global summary
(`eco/reports/sta_*.rpt`, `eco/reports/sta.md`). Only setup fails the step (before placement a hold violation is reported, not fixed). A setup
violation gets a timing fix: a read-only LLM stage writes netlist edits (sizing, buffering; checked like the patch) to
`eco/patch/sta_fix_<n>.tcl`, eco_apply applies them after the patch, then EQ(2) and this step run again — bounded by `max_rounds`."""
from __future__ import annotations

import shutil
from pathlib import Path

from q3tui.flows import skill_sections
from q3tui.flows.eco.lib import edits, tcl
from q3tui.flows.eco.lib.base import EQ2_JSON, STA_JSON, EcoStep
from q3tui.pipeline.base import StepContext, StepFailed

SYSTEM = skill_sections(Path(__file__).parent / "md" / "skill.md")
REPORTS = ("sta_setup.rpt", "sta_hold.rpt", "sta_constraints.rpt", "sta_global.rpt", "sta_check_timing.rpt")


def sta_md(result: dict, fixes: list[str], note: str) -> str:
    s, h = result.get("setup") or {}, result.get("hold") or {}
    lines = ["# STA of the Post NETLIST (PrimeTime)", "", f"- Verdict: **{note}**",
             f"- Setup: worst slack {s.get('slack_ns', '?')} ns ({'met' if s.get('met') else 'VIOLATED'}), {s.get('startpoint', '?')} → {s.get('endpoint', '?')}",
             f"- Hold: worst slack {h.get('slack_ns', '?')} ns ({'met' if h.get('met') else 'violated: reported only, before placement'})",
             f"- Violations: {len(result.get('setup_violations', []))} setup, {len(result.get('hold_violations', []))} hold "
             f"(`eco/reports/sta_constraints.rpt`)"]
    if fixes:
        lines += ["", "## Timing fixes applied", *[f"- `{f}`" for f in fixes]]
    worst = (result.get("setup_violations") or [])[:10]
    if worst:
        lines += ["", "## Worst setup violations", *[f"- `{v['line']}`" for v in worst]]
    return "\n".join(lines) + "\n"


class Step(EcoStep):
    name = "eco_sta"
    title = "STA of the Post NETLIST (PrimeTime)"
    deps = ("eco_eq2",)
    tool_roles = ("eco_sta",)
    hashed_options = ("sdc", "max_paths")

    def sdc(self, engine) -> Path | None:
        if self.options.get("sdc"):
            return engine.project.root / str(self.options["sdc"])
        if self.org_sdc(engine).is_file():
            return self.org_sdc(engine)
        tcl_sdc = engine.project.sdc_dir / "sdc.tcl"
        return tcl_sdc if tcl_sdc.is_file() else None

    def inputs(self, engine) -> list[Path]:
        sdc = self.sdc(engine)
        return [self.post_netlist(engine), self.artifact(engine, EQ2_JSON), *([sdc] if sdc else [])]

    def outputs(self, engine) -> list[Path]:
        rep = self.reports_dir(engine)
        return [f for f in (self.artifact(engine, STA_JSON), rep / "sta.md", *(rep / n for n in REPORTS)) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return self.outputs(engine)

    def missing_input(self, engine) -> str | None:
        if (self.read(engine, EQ2_JSON, {}) or {}).get("status") != "equivalent":
            return "EQ(2) has to pass first (step eco_eq2)"
        return None

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        top, libs = self.top(engine), self.need_libraries(engine)
        tools = await self.need_tool(engine, "eco_sta", "module synopsys/primeTime")
        work, rep, post = self.build_dir(engine), self.reports_dir(engine), self.post_netlist(engine)
        sdc = self.sdc(engine)
        if sdc is None:
            raise StepFailed("STA not run: no constraints — set `sdc` of eco_sta, or put the .sdc beside the ORG netlist (ref/<name>/netlist/<top>.sdc)")
        for n in REPORTS:
            (work / n).unlink(missing_ok=True)
        script = work / "sta.tcl"
        script.write_text(tcl.sta_script(libs, post, top, sdc, work, int(self.options.get("max_paths") or 10)))
        ctx.emit("log", message=f"STA: PrimeTime on {project.rel(post)} with {project.rel(sdc)}…")
        self.top_name = top
        res, log = await self.run_tool(tools, "eco_sta", script, work, "pt.log")
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "sta_pt.log").write_text(log)
        for n in REPORTS:
            if (work / n).is_file():
                shutil.copyfile(work / n, rep / n)
        read = lambda n: (work / n).read_text(errors="replace") if (work / n).is_file() else ""  # noqa: E731
        result = tcl.sta_result(read("sta_setup.rpt"), read("sta_hold.rpt"), read("sta_constraints.rpt"))
        fixes = [project.rel(f) for f in self.sta_fixes(engine)]
        if "Q3TUI_STA: DONE" not in log or not result["setup"]:
            from q3tui.eda import tools as toolmod
            toolmod.check_broken(res, "eco_sta")
            raise StepFailed(f"STA: no setup path in the report (constraints? log: {project.rel(rep / 'sta_pt.log')})")
        if result["hold_violations"] or not (result["hold"] or {}).get("met", True):
            ctx.emit("warning", message=f"STA: hold violated (worst {result['hold'].get('slack_ns', '?')} ns) — reported only, before placement")
        if result["setup_ok"]:
            (rep / "sta.md").write_text(sta_md(result, fixes, "PASS"))
            self.write(engine, STA_JSON, {"status": "pass", **result, "fixes": fixes})
            ctx.emit("log", message=f"STA: setup met (worst slack {result['setup'].get('slack_ns')} ns)")
            self.reset_rounds(ctx)
            return
        meta, n = self.rounds(ctx)
        if n >= self.round_limit(ctx):
            self.reset_rounds(ctx)
            (rep / "sta.md").write_text(sta_md(result, fixes, f"FAIL after {n} fix round(s)"))
            self.write(engine, STA_JSON, {"status": "fail", **result, "fixes": fixes})
            raise StepFailed(f"STA: setup still violated after {n} fix round(s) (worst {result['setup'].get('slack_ns')} ns): see eco/reports/sta.md")
        net = post
        task = "\n".join([f"## Setup violations of the Post NETLIST {project.rel(net)} (top `{top}`, constraints {project.rel(sdc)})",
                          f"Worst slack {result['setup'].get('slack_ns')} ns, {result['setup'].get('startpoint')} → {result['setup'].get('endpoint')}.",
                          f"Read the paths in {project.rel(rep / 'sta_setup.rpt')} and the violators in {project.rel(rep / 'sta_constraints.rpt')}; "
                          f"Grep the netlist for the cells on them.", edits.cells_block(net),
                          *(["", "Timing fixes already applied (in order): " + ", ".join(fixes)] if fixes else [])])
        eco = self.eco_dir(engine)
        out = await edits.write_edits(self, ctx, "eco_sta_fix", SYSTEM["FIX"], task, [project.build_dir, project.src_dir / "tb", project.tb_dir, eco / "org"],
                                    netlist=net)
        fix = self.patch_dir(engine) / f"sta_fix_{len(fixes) + 1}.tcl"
        fix.parent.mkdir(parents=True, exist_ok=True)
        notes = "".join(f"# {ln}\n" for ln in out.notes.splitlines() if ln.strip())
        fix.write_text(tcl.edits_text(out.commands, f"eco_sta timing fix {len(fixes) + 1}") + ("#\n" + notes if notes else ""))
        (rep / "sta.md").write_text(sta_md(result, [*fixes, project.rel(fix)], f"FAIL → timing fix {project.rel(fix)} (round {n + 1})"))
        self.write(engine, STA_JSON, {"status": "fixing", **result, "fixes": [*fixes, project.rel(fix)]})
        self.hand_back(ctx, "eco_apply", f"From eco_sta: setup violated (worst {result['setup'].get('slack_ns')} ns); apply the timing fix {project.rel(fix)}.")
        ctx.emit("warning", message=f"STA: setup violated (worst {result['setup'].get('slack_ns')} ns) → timing fix {project.rel(fix)}, round {n + 1}")
