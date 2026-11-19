"""Task `concerns` of eco_spec: each concern the AI raised about its spec change is a question to you (keep the change, or your answer, which
becomes a change request); a run that only takes your answers changes nothing."""
from __future__ import annotations

from q3tui.flows.eco.lib.base import SPEC_JSON
from q3tui.pipeline.base import StepContext

TASK = ("concerns", "each concern of the AI about its change asked to you: keep the change, or your answer as a change request")


def answers(step, ctx: StepContext, s) -> tuple[dict, list[str]] | None:
    """(the concern questions, the change requests: the run's and your answers); None when this run only took your answers (each kept, or
    still open): the record is updated and the step ends."""
    asks, answered, open_ = step.concern_answers(ctx, s.prev, s.key)
    feedback = [*ctx.feedback, *answered]
    if asks and not feedback and not ctx.regenerate:  # (a run for your answers to the concerns: each one kept, or still open)
        step.write(ctx.engine, SPEC_JSON, {**s.prev, "concern_asks": asks})
        step.task(ctx, "concerns", f"answer {', '.join(open_)}" if open_ else "every concern answered: the change is kept",
                  "waiting" if open_ else "done")
        ctx.emit("warning" if open_ else "log", message=f"spec update: answer {', '.join(open_)} (the concerns of the change), then run again"
                 if open_ else "spec update: every concern answered — the change is kept")
        return None
    return asks, feedback


def ask(step, ctx: StepContext, s, diff: str, concerns: list[str]) -> dict:
    """The questions on the concerns of this change (with the ones still kept from before)."""
    new = step.ask_concerns(ctx, {"key": s.key, "diff": diff}, concerns, "spec update")
    step.task(ctx, "concerns", f"{len(new)} asked" if new else "none", "waiting" if new else "done")
    return {**s.asks, **new}
