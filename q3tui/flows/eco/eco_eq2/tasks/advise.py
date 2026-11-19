"""Task `advise` of eco_eq2: not equivalent, an LLM (prompt: `advise.md`) reads the report with the RTL change and the patch
(`eco/reports/eq2.md`: causes, who owns the fix, the recommended fix)."""
from __future__ import annotations

from q3tui.flows.eco.lib import eq
from q3tui.flows.eco.lib.base import task_prompt
from q3tui.flows.eco.lib.models import EqAdvice
from q3tui.pipeline.base import StepContext

TASK = ("advise", "AI, when not equivalent: why, and which step fixes it (eco_rtl or eco_patch)")
PROMPT = task_prompt(__file__)
STEP_OF = {"rtl": "eco_rtl"}  # the analysis' owner -> the step that fixes it (patch, netlist, setup, unclear: the patch)


async def run(step, ctx: StepContext, result: dict, prev: dict) -> tuple[EqAdvice, str]:
    """(the analysis, the step its recommended fix goes to)."""
    engine, project = ctx.engine, ctx.project
    rep = step.reports_dir(engine)
    advice = await eq.advise(step, ctx, PROMPT,
                             f"EQ(2): RTL(F) (reference, {project.rel(step.rtl_f_filelist(engine))}) against the Post NETLIST "
                             f"{project.rel(step.post_netlist(engine))} (the ORG netlist {project.rel(step.org_netlist(engine))} with the patch "
                             f"{project.rel(step.patch_file(engine))}) is {result['status'].replace('_', ' ')}. Why, and who fixes it?",
                             [rep / "eq2_lec.rpt", rep / "eq2_fm.log", step.rtl_diff(engine), step.patch_file(engine)])
    auto = list(prev.get("auto") or [])  # (the fixes auto-answer sent since EQ(2) last passed)
    (rep / "eq2.md").write_text(eq.advice_md("EQ(2): RTL(F) vs Post NETLIST — FAILED", result, advice)
                                + "".join(f"\nAuto-answer round {a['round']}: the recommended fix went to `{a['to']}`: {a['fix']}\n" for a in auto))
    rec = STEP_OF.get(advice.owner, "eco_patch")
    step.task(ctx, "advise", f"{advice.summary} → {rec}")
    return advice, rec
