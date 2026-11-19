"""Task `plan` of eco_rtl: before any edit a read-only LLM stage plans the smallest change (an ECO changes as little as it can): the change,
what it costs in the netlist, and a smaller way when the request prescribes one. Kept in `schemas/eco_rtl_plan.json` with the request it
answers until the change is made (the same request is not planned again)."""
from __future__ import annotations

from pathlib import Path

from q3tui.core.project import sha256_json
from q3tui.flows.eco.eco_rtl.check_requirement.task import PLAN_JSON
from q3tui.flows.eco.lib.base import task_prompt
from q3tui.flows.eco.lib.models import RtlPlan
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext

TASK = ("plan", "AI, read-only: the smallest RTL change for the requirement and what it costs in the netlist (a smaller way when the "
                "request prescribes one)")
PROMPT = task_prompt(__file__)


def denied(step, engine) -> list[Path]:
    project, eco = engine.project, step.eco_dir(engine)
    return [project.build_dir, step.org_dir(engine), eco / "org", eco / "netlist", eco / "patch", project.src_dir / "tb", project.tb_dir]


def spec_part(step, engine) -> list[str]:
    """Project mode: the spec update the RTL follows (eco_spec), as a diff against the ORG spec."""
    d = step.spec_diff(engine)
    if step.mode(engine) != "project" or not d.is_file() or not d.read_text().strip():
        return []
    return [f"## The spec update of this ECO ({engine.project.rel(d)}, against the ORG spec in ref/)", d.read_text(errors="replace"), ""]


def qkey(r) -> str:
    """The request a plan answers (the requirement, the ORG RTL and the change requests)."""
    return sha256_json({"key": r.key, "feedback": r.feedback})[:16]


async def run(step, ctx: StepContext, r) -> dict:
    """The plan for this request: the one kept for it, else a new one (the LLM stage)."""
    engine, project = ctx.engine, ctx.project
    q = qkey(r)
    pending = step.read(engine, PLAN_JSON, {}) or {}
    if pending.get("qkey") == q:
        step.task(ctx, "plan", f"the plan made for this request before: {pending.get('netlist_impact', '')}")
        return pending
    task = [f"## The requirement ({project.rel(r.req)})", r.req.read_text(errors="replace"), "", *spec_part(step, engine),
            f"## The RTL to change (top `{step.top(engine)}`; " + ("the current RTL(F)" if r.update else "copies of the ORG RTL") + ")",
            *[f"- {f}" for f in r.mapping]]
    if r.update:
        task += ["", "## Change requests on this RTL(F)", *[f"- {x}" for x in r.feedback],
                 f"(The changes made so far against the ORG RTL: {project.rel(step.rtl_diff(engine))}.)"]
    stage = Stage(name="eco_rtl_plan", system_prompt=PROMPT, prompt="\n".join(task), cwd=project.root,
                  builtin_tools=["Read", "Grep", "Glob"], output_model=RtlPlan,
                  deny_dirs=denied(step, engine))
    plan: RtlPlan = (await ctx.llm(stage)).output
    pending = {"qkey": q, "key": r.key, "feedback": r.feedback, **plan.model_dump()}
    step.write(engine, PLAN_JSON, pending)
    step.task(ctx, "plan", f"{plan.plan} — netlist: {plan.netlist_impact}")
    return pending
