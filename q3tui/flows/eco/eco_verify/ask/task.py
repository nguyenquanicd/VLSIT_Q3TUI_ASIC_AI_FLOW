"""Task `ask` of eco_verify: whether Verification (the dv flow) and Sanity run again on the ECO'd design before the netlist ECO (the `verify`
option answers for you; auto-answer takes yes). External mode (a fire-fighting ECO) and "no": the step is skipped."""
from __future__ import annotations

from q3tui.flows.eco.lib.base import VERIFY_JSON, answer_is
from q3tui.pipeline.base import StepContext

TASK = ("ask", "run dv + Sanity again on the ECO'd design? (ECOVER)")
YES, NO = "Yes, run dv and Sanity again", "No, go on to the netlist ECO"


def wanted(step, ctx: StepContext) -> bool | None:
    opt = step.options.get("verify")
    if opt is not None:
        return str(opt).strip().lower() in ("1", "true", "yes", "on")
    qid, answer = step.decide(ctx, "verify", "ECOVER", (
        "The ECO changed this project's RTL (and spec). Run Verification (the dv flow) and Sanity (CDC / RDC) again on it before the netlist "
        "ECO? Yes: both must pass first; their RTL fixes come back to eco_rtl as the smallest change."),
        [(f"{YES} (Recommended)", "the netlist ECO starts only when dv and Sanity pass on the new RTL"),
         (NO, "the netlist ECO goes on; dv / Sanity are yours to run later")])
    if answer is None:
        ctx.emit("warning", message=f"ECO verify: answer {qid} (run dv + Sanity again or not), then run again")
        return None
    return not answer_is(answer, "no")


def run(step, ctx: StepContext) -> bool:
    """True: dv and Sanity run next; False: the step ends here (external RTL, your no, or the answer awaited)."""
    engine = ctx.engine
    if step.mode(engine) != "project":
        step.write(engine, VERIFY_JSON, {"status": "skipped", "why": "external RTL: a fire-fighting ECO, no dv / Sanity request"})
        ctx.emit("log", message="ECO verify: skipped (external RTL)")
        step.task(ctx, "ask", "skipped: external RTL (a fire-fighting ECO)", "skipped")
        _not_run(step, ctx, "external RTL")
        return False
    yes = wanted(step, ctx)
    if yes is None:
        step.write(engine, VERIFY_JSON, {"status": "waiting"})
        step.task(ctx, "ask", "answer the question (ECOVER)", "waiting")
        return False
    if not yes:
        step.write(engine, VERIFY_JSON, {"status": "skipped", "why": "your choice: dv / Sanity not run again"})
        ctx.emit("log", message="ECO verify: skipped (your choice)")
        step.task(ctx, "ask", "no: go on without dv / Sanity")
        _not_run(step, ctx, "your choice")
        return False
    step.task(ctx, "ask", "yes: dv and Sanity run")
    return True


def _not_run(step, ctx: StepContext, why: str) -> None:
    for flow in ("dv", "sanity"):
        step.task(ctx, flow, f"not run: {why}", "skipped")
