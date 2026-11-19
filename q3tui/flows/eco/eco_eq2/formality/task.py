"""Task `formality` of eco_eq2: Formality checks the ECO NETLIST against RTL(F); equivalent: the step is done (advise and route not needed)."""
from __future__ import annotations

from q3tui.flows.eco.lib import eq
from q3tui.flows.eco.lib.base import EQ2_JSON
from q3tui.pipeline.base import StepContext

TASK = ("formality", "Formality: RTL(F) against the ECO NETLIST")


async def run(step, ctx: StepContext, asks: dict) -> dict | None:
    """The result when not equivalent (advise and route follow); None when equivalent (recorded, the step is done)."""
    engine = ctx.engine
    result = await eq.run_formality(step, ctx, step.rtl_f_files(engine), step.eco_netlist(engine), "eq2")
    step.task(ctx, "formality", f"{result['status'].replace('_', ' ')} ({result.get('passing', '?')} passing, {result.get('failing', 0)} failing)",
              "done" if result["status"] == "equivalent" else "failed")
    if result["status"] != "equivalent":
        return result
    (step.reports_dir(engine) / "eq2.md").write_text(eq.advice_md("EQ(2): RTL(F) vs ECO NETLIST", result, None))
    step.write(engine, EQ2_JSON, {**result, "asks": asks})
    ctx.emit("log", message=f"EQ(2): equivalent ({result.get('passing', '?')} compare points)")
    step.task(ctx, "advise", "not needed: equivalent", "skipped")
    step.task(ctx, "route", "not needed: equivalent", "skipped")
    step.reset_rounds(ctx)
    return None
