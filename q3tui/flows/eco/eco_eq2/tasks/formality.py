"""Task `formality` of eco_eq2: EQ(2), the Post NETLIST against RTL(F) (Formality)."""
from __future__ import annotations

from q3tui.flows.eco.lib import eq
from q3tui.flows.eco.lib.base import EQ2_JSON
from q3tui.pipeline.base import StepContext

TASK = ("formality", "Formality: RTL(F) against the Post NETLIST")


async def run(step, ctx: StepContext, asks: dict) -> dict | None:
    """Formality's result when not equivalent (for `advise`); None when EQ(2) passed (the result written)."""
    engine = ctx.engine
    result = await eq.run_formality(step, ctx, step.rtl_f_files(engine), step.post_netlist(engine), "eq2")
    rep = step.reports_dir(engine)
    step.task(ctx, "formality", f"{result['status']} ({result.get('passing', '?')} passing, {result.get('failing', 0)} failing)",
              "done" if result["status"] == "equivalent" else "failed")
    if result["status"] == "equivalent":
        (rep / "eq2.md").write_text(eq.advice_md("EQ(2): RTL(F) vs Post NETLIST", result, None))
        step.write(engine, EQ2_JSON, {**result, "asks": asks})
        ctx.emit("log", message=f"EQ(2): equivalent ({result.get('passing', '?')} compare points)")
        step.reset_rounds(ctx)
        return None
    return result
