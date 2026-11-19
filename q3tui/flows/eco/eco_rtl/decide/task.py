"""Task `decide` of eco_rtl: when the requirement or a change request prescribes how to make the change and the plan finds a smaller one
with the same required function, you are asked (blocking): the smaller change (recommended; auto-answer takes it), the change as asked, or
your own words. The decision is kept with the plan of the request it answers."""
from __future__ import annotations

from q3tui.flows.eco.eco_rtl.check_requirement.task import PLAN_JSON
from q3tui.flows.eco.eco_rtl.plan.task import qkey
from q3tui.flows.eco.lib.base import answer_is
from q3tui.pipeline.base import StepContext

TASK = ("decide", "when a smaller change than the one asked gives the same function: you choose (ECORTL; the smaller one recommended)")
USE_ALT, KEEP, OWN = "Use the smaller change", "Keep the change as asked", "My own way"


def chosen_change(answer: str, plan: dict) -> str:
    """The change to make, from your answer to the smaller-change question."""
    alt = plan.get("alternative") or {}
    if answer_is(answer, USE_ALT, "smaller", "use"):
        return f"{alt.get('change', '')} (the smaller change, chosen by the user: {alt.get('differs_from_request', '')})"
    if answer_is(answer, KEEP, "keep", "as asked"):
        return f"{plan.get('requested') or plan.get('plan', '')} (as asked: the user declined the smaller change)"
    text = answer.strip()
    if answer_is(text, OWN):
        text = text[len(OWN):].lstrip(" :-").strip()
    return f"{text} (the user's own way)"


def run(step, ctx: StepContext, r, pending: dict) -> str | None:
    """The change to make: the plan's, or your choice (None while your answer is awaited)."""
    alt = pending.get("alternative")
    if not alt:
        step.task(ctx, "decide", "nothing to decide: no smaller change than the one asked", "skipped")
        return pending["plan"]
    asked = pending.get("requested") or "the change as the requirement / change request describes it"
    qid, answer = step.decide(ctx, f"alt:{qkey(r)}", "ECORTL", (
        f"RTL(F): the request asks for {asked}. A smaller change gives the same required function: {alt['change']} — smaller because "
        f"{alt['smaller_because']}; same function because {alt['same_function_because']}. It differs from the request: "
        f"{alt['differs_from_request']}. Which change should RTL(F) make?"),
        [(f"{USE_ALT} (Recommended): {alt['change']}", "fewer netlist edits; the requirement's function is kept"),
         (f"{KEEP}: {asked}", "exactly what was asked"),
         (f"{OWN}: <type how to change it>", "your words go to the RTL edit")])
    if answer is None:
        step.task(ctx, "decide", f"answer {qid}: a smaller change than the one asked exists", "waiting")
        ctx.emit("warning", message=f"RTL(F): a smaller change than the one asked exists — answer {qid} (see schemas/{PLAN_JSON})")
        return None
    pending["decision"] = {"question": qid, "answer": answer}
    step.write(ctx.engine, PLAN_JSON, pending)
    step.task(ctx, "decide", f"{qid or 'auto-answer'}: {answer}")
    ctx.emit("log", message=f"RTL(F): {qid or 'auto-answer'} → {answer[:120]}")
    return chosen_change(answer, pending)
