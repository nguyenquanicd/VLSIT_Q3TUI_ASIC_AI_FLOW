"""Task `hand-off` of eco_spec: when the spec flow wrote `spec/spec.md`, the request goes to the spec flow's `spec` step and the spec flow
runs (spec → parse → config: it patches only the sections the request affects; its gate and questions are its own: when it stops there,
this step fails until you finished there and run eco again — the request is not sent twice)."""
from __future__ import annotations

from q3tui.flows.eco.eco_spec.tasks import request
from q3tui.flows.eco.lib.models import RtlUpdate
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("hand-off", "the spec flow wrote spec/spec.md: the request to its `spec` step, the spec flow run (spec → parse → config)")


async def run(step, ctx: StepContext, r: request.Request) -> RtlUpdate:
    """The request to the spec flow's `spec` step, then the spec flow run (spec → parse → config)."""
    requests = [request.text(ctx.project, r.req), *[f"ECO change request on the updated spec: {x}" for x in r.feedback]]
    outcome = await step.hand_to_owner(ctx, "spec", "spec", requests, r.qkey)
    if outcome != "complete":
        step.task(ctx, "hand-off", f"spec flow: {outcome}", "waiting")
        raise StepFailed(f"the spec flow has the ECO change but ended '{outcome}': finish it there (q3tui --flow spec, F in the TUI: "
                         f"review / answer), then run eco again (the change is not sent twice)")
    step.task(ctx, "hand-off", f"spec flow done ({len(requests)} request(s) to its spec step)")
    return RtlUpdate(summary="the spec flow updated spec/spec.md to the requirement", changes=[{"file": "spec/spec.md", "what": "by the spec flow"}])
