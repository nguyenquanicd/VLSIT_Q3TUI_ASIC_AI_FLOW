"""Task `fix` of eco_sta: a setup violation gets a timing fix — a read-only LLM stage (prompt.md) writes netlist edits (sizing, buffering;
checked like the patch) to `eco/patch/sta_fix_<n>.tcl`; eco_apply applies them after the patch, then EQ(2) and STA run again — bounded by
`max_rounds`."""
from __future__ import annotations

from q3tui.flows.eco.eco_sta.primetime.task import sta_md
from q3tui.flows.eco.lib import edits, tcl
from q3tui.flows.eco.lib.base import STA_JSON, task_prompt
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("fix", "AI, when setup is violated: a timing fix (sizing / buffering netlist edits) → eco_apply")
PROMPT = task_prompt(__file__)


async def run(step, ctx: StepContext, sta: dict) -> None:
    engine, project = ctx.engine, ctx.project
    result, fixes, sdc, top = sta["result"], sta["fixes"], sta["sdc"], sta["top"]
    rep, net = step.reports_dir(engine), step.eco_netlist(engine)
    meta, n = step.rounds(ctx)
    if n >= step.round_limit(ctx):
        step.reset_rounds(ctx)
        (rep / "sta.md").write_text(sta_md(result, fixes, f"FAIL after {n} fix round(s)"))
        step.write(engine, STA_JSON, {"status": "fail", **result, "fixes": fixes})
        step.task(ctx, "fix", f"fix rounds used up ({n})", "failed")
        raise StepFailed(f"STA: setup still violated after {n} fix round(s) (worst {result['setup'].get('slack_ns')} ns): see eco/reports/sta.md")
    task = "\n".join([f"## Setup violations of the ECO NETLIST {project.rel(net)} (top `{top}`, constraints {project.rel(sdc)})",
                      f"Worst slack {result['setup'].get('slack_ns')} ns, {result['setup'].get('startpoint')} → {result['setup'].get('endpoint')}.",
                      f"Read the paths in {project.rel(rep / 'sta_setup.rpt')} and the violators in {project.rel(rep / 'sta_constraints.rpt')}; "
                      f"Grep the netlist for the cells on them.", edits.cells_block(net),
                      *(["", "Timing fixes already applied (in order): " + ", ".join(fixes)] if fixes else [])])
    eco = step.eco_dir(engine)
    try:
        out = await edits.write_edits(step, ctx, "eco_sta_fix", PROMPT, task,
                                      [project.build_dir, project.src_dir / "tb", project.tb_dir, eco / "org"], netlist=net)
    except StepFailed as e:
        step.task(ctx, "fix", str(e), "failed")
        raise
    fix = step.patch_dir(engine) / f"sta_fix_{len(fixes) + 1}.tcl"
    fix.parent.mkdir(parents=True, exist_ok=True)
    notes = "".join(f"# {ln}\n" for ln in out.notes.splitlines() if ln.strip())
    fix.write_text(tcl.edits_text(out.commands, f"eco_sta timing fix {len(fixes) + 1}") + ("#\n" + notes if notes else ""))
    (rep / "sta.md").write_text(sta_md(result, [*fixes, project.rel(fix)], f"FAIL → timing fix {project.rel(fix)} (round {n + 1})"))
    step.write(engine, STA_JSON, {"status": "fixing", **result, "fixes": [*fixes, project.rel(fix)]})
    step.hand_back(ctx, "eco_apply", f"From eco_sta: setup violated (worst {result['setup'].get('slack_ns')} ns); apply the timing fix {project.rel(fix)}.")
    step.task(ctx, "fix", f"{project.rel(fix)} ({len(out.commands)} edit(s)) → eco_apply, round {n + 1}", "handed")
    ctx.emit("warning", message=f"STA: setup violated (worst {result['setup'].get('slack_ns')} ns) → timing fix {project.rel(fix)}, round {n + 1}")
