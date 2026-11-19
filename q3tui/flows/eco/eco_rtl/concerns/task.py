"""Task `concerns` of eco_rtl: each concern the AI raised about its RTL change is a question to you (keep the change, or your answer, which
becomes a change request); a run that only takes your answers changes nothing."""
from __future__ import annotations

from q3tui.flows.eco.lib.base import RTL_JSON
from q3tui.pipeline.base import StepContext

TASK = ("concerns", "each concern of the AI about its change asked to you: keep the change, or your answer as a change request")


def answers(step, ctx: StepContext, r, pending: dict) -> tuple[dict, list[str]] | None:
    """(the concern questions, the change requests: the run's, your answers, or the ones a pending plan question was about); None when this
    run only took your answers (each kept, or still open): the record is updated and the step ends."""
    engine = ctx.engine
    asks, answered, open_ = step.concern_answers(ctx, r.prev, r.key)
    if answered:  # (your answers to the concerns: change requests from now on, kept in the plan if it asks first)
        step.write(engine, RTL_JSON, {**r.prev, "concern_asks": asks})
    feedback = [*ctx.feedback, *answered]
    if not feedback and pending.get("key") == r.key and pending.get("feedback") and not ctx.regenerate:
        feedback = list(pending["feedback"])  # (the change requests the question was about: consumed by the run that asked)
    if asks and not feedback and not ctx.regenerate:  # (a run for your answers to the concerns: each one kept, or still open)
        step.write(engine, RTL_JSON, {**r.prev, "concern_asks": asks})
        step.task(ctx, "concerns", f"answer {', '.join(open_)}" if open_ else "every concern answered: the change is kept",
                  "waiting" if open_ else "done")
        ctx.emit("warning" if open_ else "log", message=f"RTL(F): answer {', '.join(open_)} (the concerns of the change), then run again"
                 if open_ else "RTL(F): every concern answered — the change is kept")
        return None
    return asks, feedback


def ask(step, ctx: StepContext, r, diff: str, concerns: list[str]) -> dict:
    """The questions on the concerns of this change (with the ones still kept from before)."""
    new = step.ask_concerns(ctx, {"key": r.key, "diff": diff}, concerns, "RTL(F)")
    step.task(ctx, "concerns", f"{len(new)} asked" if new else "none", "waiting" if new else "done")
    return {**r.asks, **new}
