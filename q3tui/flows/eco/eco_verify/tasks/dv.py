"""Task `dv` of eco_verify: the dv flow run on this project (its own engine) within this step; every test must pass. Its RTL / spec fixes
come back to this flow (`eco_rtl` / `eco_spec`: lib/ref.py `eco_owner`), never to the rtl flow's generator."""
from __future__ import annotations

from q3tui.core.project import read_json
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("dv", "the dv flow run: every test must pass")
NOT_PASSED = ("FAIL", "ERROR", "TIMEOUT", "BLOCKED")


async def other(step, ctx: StepContext, name: str, yes: bool) -> str:
    """Run the flow `name` on this project (its own engine; this one saved before, its requests pulled after)."""
    from q3tui import flows
    from q3tui.pipeline.engine import Engine
    ctx.engine.save()
    try:
        flow = Engine(ctx.project, ctx.engine.bus, flow=flows.load_flow(name, ctx.project.root))
        try:
            return await flow.run(yes=yes)
        except StepFailed as exc:
            return f"failed: {exc}"
    finally:
        step.pull_requests(ctx)


def left(ctx, name: str) -> list[str]:
    from q3tui import flows
    from q3tui.pipeline.engine import Engine
    views = Engine(ctx.project, flow=flows.load_flow(name, ctx.project.root)).status()
    return [f"{v.name} ({v.status})" for v in views if v.status not in ("done", "user")]


async def run(step, ctx: StepContext, yes: bool) -> tuple[bool, str]:
    outcome = await other(step, ctx, "dv", yes)
    not_done = left(ctx, "dv")
    tests = (read_json(ctx.project.schemas_dir / "dv_test_results.json", {}) or {}).get("tests", [])
    bad = [f"{t.get('name') or t.get('tc_id')}: {t.get('status')}" for t in tests if t.get("status") in NOT_PASSED]
    if outcome == "complete" and not not_done and not bad and tests:
        return True, f"{len(tests)} test(s) passed"
    return False, (f"ended '{outcome}'" + (f"; not done: {', '.join(not_done[:5])}" if not_done else "")
                   + (f"; {len(bad)} test(s) not passing: {', '.join(bad[:5])}" if bad else "") + ("" if tests else "; no test result"))
