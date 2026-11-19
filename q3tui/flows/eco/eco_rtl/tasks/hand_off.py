"""Task `hand-off` of eco_rtl (project mode, RTL the rtl flow made): the planned change goes to the rtl flow's `rtl` step as one change
request per module (`[rtl:<module>]`), and the rtl flow runs (it edits src/rtl, lints and smoke-tests; its gate and questions are its own:
when it stops there, this step fails until you finished there and run eco again — the request is not sent twice)."""
from __future__ import annotations

from q3tui.flows.eco.eco_rtl.tasks.check import parse_errors
from q3tui.flows.eco.lib.base import task_prompt
from q3tui.flows.eco.lib.models import RtlUpdate
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("hand-off", "project mode, RTL the rtl flow made: the change to the rtl flow's `rtl` step ([rtl:<module>]), the rtl flow run")
PROMPT = task_prompt(__file__)


def owner_modules(step, engine, modules: list[str]) -> list[str]:
    """The modules to hand to the rtl flow: all those the plan edits, when the rtl flow made each of them; else none (edited here)."""
    made = (engine.state.step_meta.get("rtl") or {}).get("modules") or {}
    if not modules or not step.owner_made(engine, "rtl") or any(m not in made for m in modules):
        return []
    return modules


async def run(step, ctx: StepContext, change: str, modules: list[str], qkey: str) -> RtlUpdate:
    """The planned change to the rtl flow's `rtl` step (one request per module), then the rtl flow run; its result must parse."""
    from q3tui.steps.common import scoped
    text = PROMPT.replace("{change}", change.strip())
    outcome = await step.hand_to_owner(ctx, "rtl", "rtl", [scoped("rtl", m, text) for m in modules], qkey)
    if outcome != "complete":
        step.task(ctx, "hand-off", f"rtl flow: {outcome}", "waiting")
        raise StepFailed(f"the rtl flow has the ECO change ({', '.join(modules)}) but ended '{outcome}': finish it there (q3tui --flow rtl, "
                         f"F in the TUI: review / answer / fix), then run eco again (the change is not sent twice)")
    step.task(ctx, "hand-off", f"rtl flow done: {', '.join(f'[rtl:{m}]' for m in modules)}")
    problems = parse_errors(step, ctx.engine)
    if problems:
        step.task(ctx, "check", "; ".join(problems[:3]), "failed")
        raise StepFailed("RTL(F) from the rtl flow does not parse: " + "; ".join(problems[:5]))
    return RtlUpdate(summary=change, changes=[{"file": m, "what": "by the rtl flow ([rtl:" + m + "])"} for m in modules])
