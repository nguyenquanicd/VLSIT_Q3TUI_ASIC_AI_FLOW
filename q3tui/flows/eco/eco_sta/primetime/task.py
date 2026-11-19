"""Task `primetime` of eco_sta: STA of the ECO NETLIST with PrimeTime (tool role `eco_sta`): setup and hold paths, all violators, the global
summary (`eco/reports/sta_*.rpt`, `eco/reports/sta.md`). Only setup fails the step (before placement a hold violation is reported, not fixed)."""
from __future__ import annotations

import shutil

from q3tui.flows.eco.lib import tcl
from q3tui.flows.eco.lib.base import STA_JSON
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("primetime", "PrimeTime on the ECO NETLIST with the ORG constraints: setup / hold (hold reported only, before placement)")
REPORTS = ("sta_setup.rpt", "sta_hold.rpt", "sta_constraints.rpt", "sta_global.rpt", "sta_check_timing.rpt")


def sta_md(result: dict, fixes: list[str], note: str) -> str:
    s, h = result.get("setup") or {}, result.get("hold") or {}
    lines = ["# STA of the ECO NETLIST (PrimeTime)", "", f"- Verdict: **{note}**",
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


async def run(step, ctx: StepContext) -> dict | None:
    """The STA when setup is violated (the fix task follows): {result, fixes, sdc, top}; None when setup is met (recorded, the step is done)."""
    engine, project = ctx.engine, ctx.project
    top, libs = step.top(engine), step.need_libraries(engine)
    tools = await step.need_tool(engine, "eco_sta", "module synopsys/primeTime")
    work, rep, post = step.build_dir(engine), step.reports_dir(engine), step.eco_netlist(engine)
    sdc = step.sdc(engine)
    if sdc is None:
        step.task(ctx, "primetime", "not run: no constraints", "failed")
        raise StepFailed("STA not run: no constraints — set `sdc` of eco_sta, or put the .sdc beside the ORG netlist (ref/<name>/netlist/<top>.sdc)")
    for n in REPORTS:
        (work / n).unlink(missing_ok=True)
    script = work / "sta.tcl"
    script.write_text(tcl.sta_script(libs, post, top, sdc, work, int(step.options.get("max_paths") or 10)))
    ctx.emit("log", message=f"STA: PrimeTime on {project.rel(post)} with {project.rel(sdc)}…")
    step.top_name = top
    res, log = await step.run_tool(tools, "eco_sta", script, work, "pt.log")
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "sta_pt.log").write_text(log)
    for n in REPORTS:
        if (work / n).is_file():
            shutil.copyfile(work / n, rep / n)
    read = lambda n: (work / n).read_text(errors="replace") if (work / n).is_file() else ""  # noqa: E731
    result = tcl.sta_result(read("sta_setup.rpt"), read("sta_hold.rpt"), read("sta_constraints.rpt"))
    fixes = [project.rel(f) for f in step.sta_fixes(engine)]
    if "Q3TUI_STA: DONE" not in log or not result["setup"]:
        step.task(ctx, "primetime", "no setup path in the report", "failed")
        from q3tui.eda import tools as toolmod
        toolmod.check_broken(res, "eco_sta")
        raise StepFailed(f"STA: no setup path in the report (constraints? log: {project.rel(rep / 'sta_pt.log')})")
    step.task(ctx, "primetime", f"setup {result['setup'].get('slack_ns')} ns, hold {(result['hold'] or {}).get('slack_ns', '?')} ns",
              "done" if result["setup_ok"] else "failed")
    if result["hold_violations"] or not (result["hold"] or {}).get("met", True):
        ctx.emit("warning", message=f"STA: hold violated (worst {result['hold'].get('slack_ns', '?')} ns) — reported only, before placement")
    if not result["setup_ok"]:
        return {"result": result, "fixes": fixes, "sdc": sdc, "top": top}
    (rep / "sta.md").write_text(sta_md(result, fixes, "PASS"))
    step.write(engine, STA_JSON, {"status": "pass", **result, "fixes": fixes})
    ctx.emit("log", message=f"STA: setup met (worst slack {result['setup'].get('slack_ns')} ns)")
    step.task(ctx, "fix", "not needed: setup met", "skipped")
    step.reset_rounds(ctx)
    return None
