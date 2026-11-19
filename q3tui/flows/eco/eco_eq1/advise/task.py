"""Task `advise` of eco_eq1: when EQ(1) is not equivalent, the AI reads Formality's report and log and says why and what to do
(`eco/reports/eq1.md`); the flow stops."""
from __future__ import annotations

from q3tui.flows.eco.lib import eq
from q3tui.flows.eco.lib.base import EQ1_JSON, task_prompt
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("advise", "AI, when not equivalent: why, and what to do (eco/reports/eq1.md)")
PROMPT = task_prompt(__file__)


async def run(step, ctx: StepContext, inputs: dict, result: dict, qid: str) -> None:
    engine, project = ctx.engine, ctx.project
    rep = step.reports_dir(engine)
    advice = await eq.advise(step, ctx, PROMPT,
                             f"EQ(1): the ORG RTL (reference, filelist {inputs.get('rtl')}) against the ORG netlist {project.rel(step.org_netlist(engine))} "
                             f"(implementation) is {result['status'].replace('_', ' ')}. Why, and what to do?",
                             [rep / "eq1_lec.rpt", rep / "eq1_fm.log"])
    (rep / "eq1.md").write_text(eq.advice_md("EQ(1): ORG RTL vs ORG netlist — FAILED", result, advice))
    step.write(engine, EQ1_JSON, {**result, "source": "formality", "question": qid, "advice": advice.model_dump()})
    step.task(ctx, "advise", advice.summary, "failed")
    raise StepFailed(f"EQ(1): the ORG netlist is {result['status'].replace('_', ' ')} to the ORG RTL ({result.get('failing', '?')} failing "
                     f"point(s)): {advice.summary} — see eco/reports/eq1.md")
