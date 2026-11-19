"""Task `sanity` of eco_verify: the Sanity flow (analysis, then the review's hand-off) runs on the ECO'd design within this step; nothing may
stay open. Its fixes come back to `eco_rtl` / `eco_spec`: this step hands back, the fix loop updates RTL(F) and runs this step again (bounded by
`max_rounds`). A request `eco_rtl` judged not the ECO's to fix ends here, for you to look at."""
from __future__ import annotations

from q3tui.flows.eco.eco_verify.dv.task import other, pull_requests
from q3tui.flows.eco.lib.base import RTL_JSON, VERIFY_JSON
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("sanity", "the Sanity flow run: nothing open; fixes hand back to eco_rtl / eco_spec")


async def run(step, ctx: StepContext, yes: bool) -> tuple[bool, str]:
    """(passed, what happened)."""
    from q3tui.core.loop import measure
    outcome = await other(ctx, "sanity", yes)
    if outcome not in ("complete", "gate"):
        return False, f"analysis ended '{outcome}'"
    n_open, total = measure(ctx.project)
    if n_open == 0:
        return True, f"nothing open ({total} found, all waived or fixed)"
    # (the review's fix_rtl / spec decisions: handed to this flow's eco_rtl / eco_spec while the project-mode ECO is on)
    from q3tui import flows
    from q3tui.core.ops import Ops
    from q3tui.pipeline.engine import Engine, EngineError
    ctx.engine.save()
    try:
        msg = Ops(Engine(ctx.project, ctx.engine.bus, flow=flows.load_flow("sanity", ctx.project.root))).run_action("sanity_handoff")
    except EngineError as exc:
        msg = f"nothing handed off ({exc})"
    finally:
        pull_requests(ctx)
    return False, f"{n_open} of {total} open; {msg}"


def settle(step, ctx: StepContext, results: dict[str, dict], failed: str | None) -> None:
    """The step's result after dv / Sanity: passed; or their fixes handed to eco_rtl / eco_spec (the fix loop, bounded); or failed."""
    engine = ctx.engine
    prev = step.read(engine, VERIFY_JSON, {}) or {}
    declined = len((step.read(engine, RTL_JSON, {}) or {}).get("declined", []))
    if failed is None:
        step.write(engine, VERIFY_JSON, {"status": "passed", "flows": results})
        step.reset_rounds(ctx)
        return
    fixes = {s: list(engine.state.feedback.get(s) or []) for s in ("eco_rtl", "eco_spec") if engine.state.feedback.get(s)}
    record = {"status": "fixes" if fixes else "failed", "flows": results, "handed": fixes, "declined": declined}
    meta, n = step.rounds(ctx)
    if fixes and declined > int(prev.get("declined", declined)) and prev.get("status") == "fixes":
        fixes = {}  # (eco_rtl kept the RTL for the last requests and the check still fails: not a loop to go on with)
    if fixes and n < step.round_limit(ctx):
        meta["loop"], meta["rounds"] = True, n + 1  # (the requests are queued already: eco_rtl / eco_spec update, then this step again)
        step.write(engine, VERIFY_JSON, record)
        ctx.emit("log", message=f"ECO verify: {failed} handed {sum(map(len, fixes.values()))} fix(es) to "
                                f"{', '.join(fixes)} (round {n + 1}); they run next, then dv / Sanity again")
        step.task(ctx, failed, f"{results[failed]['note']} → {', '.join(fixes)} (round {n + 1})", "handed")
        return
    record["status"] = "failed"
    step.write(engine, VERIFY_JSON, record)
    step.reset_rounds(ctx)
    last = (step.read(engine, RTL_JSON, {}) or {}).get("declined", [])
    why = f"; eco_rtl kept the RTL: {last[-1]['why'][:300]}" if last else ""
    raise StepFailed(f"ECO verify: {failed} does not pass on the ECO'd design — {results[failed]['note']}{why}. Look at it (q3tui --flow "
                     f"{failed}), then run eco again (or answer no to eco_verify's question to go on without it)")
