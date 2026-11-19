"""Task `formality` of eco_eq1: EQ(1), the ORG netlist against the ORG RTL (Formality) — or asic_lec's result taken, or skipped by your answer
(said in the result, the flow goes on)."""
from __future__ import annotations

from pathlib import Path

from q3tui.core.project import read_json
from q3tui.flows.eco.eco_eq1.tasks.decide import SKIP, USE_LEC
from q3tui.flows.eco.lib import eq
from q3tui.flows.eco.lib.base import EQ1_JSON, answer_is
from q3tui.pipeline.base import StepContext

TASK = ("formality", "Formality: the ORG RTL against the ORG netlist")


async def run(step, ctx: StepContext, rtl: list[Path], qid: str | None, answer: str, reuse: bool) -> dict | None:
    """Formality's result when not equivalent (for `advise`); None when EQ(1) passed or was skipped (the result written)."""
    engine, project = ctx.engine, ctx.project
    if reuse and answer_is(answer, USE_LEC, "use"):
        lec = read_json(project.schemas_dir / "asic_lec.json", {})
        step.write(engine, EQ1_JSON, {"status": "equivalent", "source": "asic_lec", "passing": lec.get("passing"),
                                      "report": "build/syn/asic/reports/lec.rpt", "question": qid})
        step.task(ctx, "formality", f"not run: asic_lec's result, {lec.get('passing', '?')} compare points", "skipped")
        ctx.emit("log", message=f"EQ(1): passed (asic_lec's result, {lec.get('passing', '?')} compare points)")
        return None
    if not reuse and answer_is(answer, SKIP, "skip", "no", "không"):
        step.write(engine, EQ1_JSON, {"status": "skipped", "source": "you", "question": qid})
        step.task(ctx, "formality", "skipped (your choice)", "skipped")
        ctx.emit("warning", message=f"EQ(1) skipped ({qid}): the ORG netlist is not proven equal to the ORG RTL")
        return None
    result = await eq.run_formality(step, ctx, rtl, step.org_netlist(engine), "eq1")
    step.write(engine, EQ1_JSON, {**result, "source": "formality", "question": qid})
    step.task(ctx, "formality", f"{result['status']} ({result.get('passing', '?')} passing, {result.get('failing', 0)} failing)",
              "done" if result["status"] == "equivalent" else "failed")
    if result["status"] == "equivalent":
        (step.reports_dir(engine) / "eq1.md").write_text(eq.advice_md("EQ(1): ORG RTL vs ORG netlist", result, None))
        ctx.emit("log", message=f"EQ(1): equivalent ({result.get('passing', '?')} compare points)")
        return None
    return result
