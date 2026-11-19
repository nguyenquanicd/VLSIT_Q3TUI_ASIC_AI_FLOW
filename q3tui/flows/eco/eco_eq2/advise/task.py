"""Task `advise` of eco_eq2: not equivalent — an LLM reads the report with the RTL change and the patch (prompt.md) and writes
`eco/reports/eq2.md`: the causes, who owns the fix, the recommended fix."""
from __future__ import annotations

from q3tui.flows.eco.eco_eq2.route.task import STEP_OF
from q3tui.flows.eco.lib import eq
from q3tui.flows.eco.lib.base import task_prompt
from q3tui.pipeline.base import StepContext

TASK = ("advise", "AI, when not equivalent: why, and which step fixes it (eco_rtl or eco_patch) — eco/reports/eq2.md")
PROMPT = task_prompt(__file__)


async def run(step, ctx: StepContext, result: dict, prev: dict):
    engine, project = ctx.engine, ctx.project
    rep = step.reports_dir(engine)
    advice = await eq.advise(step, ctx, PROMPT,
                             f"EQ(2): RTL(F) (reference, {project.rel(step.rtl_f_filelist(engine))}) against the ECO NETLIST "
                             f"{project.rel(step.eco_netlist(engine))} (the ORG netlist {project.rel(step.org_netlist(engine))} with the patch "
                             f"{project.rel(step.patch_file(engine))}) is {result['status'].replace('_', ' ')}. Why, and who fixes it?",
                             [rep / "eq2_lec.rpt", rep / "eq2_fm.log", step.rtl_diff(engine), step.patch_file(engine)])
    auto = list(prev.get("auto") or [])  # (the fixes auto-answer sent since EQ(2) last passed)
    (rep / "eq2.md").write_text(eq.advice_md("EQ(2): RTL(F) vs ECO NETLIST — FAILED", result, advice)
                                + "".join(f"\nAuto-answer round {a['round']}: the recommended fix went to `{a['to']}`: {a['fix']}\n" for a in auto))
    step.task(ctx, "advise", f"{advice.summary} → {STEP_OF.get(advice.owner, 'eco_patch')}")
    return advice
