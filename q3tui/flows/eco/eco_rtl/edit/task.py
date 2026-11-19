"""Task `edit` of eco_rtl: an LLM stage edits RTL(F) in place to make the decided change and nothing more (it may write only in eco/rtl/ or
the project's RTL; the netlists, the patch and build/ are denied). RTL(F) that does not parse goes back to it once with the parser's errors."""
from __future__ import annotations

from q3tui.flows.eco.eco_rtl.check.task import parse_errors
from q3tui.flows.eco.eco_rtl.plan.task import denied, spec_part
from q3tui.flows.eco.lib.base import task_prompt
from q3tui.flows.eco.lib.models import RtlUpdate
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("edit", "AI: RTL(F) edited in place to make the decided change and nothing more (once more when it does not parse)")
PROMPT = task_prompt(__file__)


async def _edit(step, ctx: StepContext, task: str) -> RtlUpdate:
    engine, project = ctx.engine, ctx.project
    stage = Stage(name="eco_rtl", system_prompt=PROMPT, prompt=task, cwd=project.root,
                  builtin_tools=["Read", "Grep", "Glob", "Edit", "Write"], output_model=RtlUpdate,
                  write_dirs=[step.rtl_f_dir(engine)],
                  deny_dirs=denied(step, engine))
    return (await ctx.llm(stage)).output


async def run(step, ctx: StepContext, r, change: str) -> RtlUpdate:
    engine, project = ctx.engine, ctx.project
    task = [f"## The requirement ({project.rel(r.req)})", r.req.read_text(errors="replace"), "", *spec_part(step, engine),
            f"## RTL(F): edit these files in place (top `{step.top(engine)}`; each is a copy of the ORG file named after it)",
            *[f"- {f} (ORG: {o})" for f, o in r.mapping.items()]]
    if r.update:
        task += ["", "## Change requests on the current RTL(F)", *[f"- {x}" for x in r.feedback],
                 "", f"The changes made so far against the ORG RTL are in {project.rel(step.rtl_diff(engine))}."]
    task += ["", "## The change to make (planned, and decided with the user when it differs from the request)", change,
             "Make this change and nothing more."]
    out = await _edit(step, ctx, "\n".join(task))
    problems = parse_errors(step, engine)
    fixed = ""
    if problems:  # one round back to the LLM with the parser's errors
        out = await _edit(step, ctx, "\n".join([*task, "", "## RTL(F) does not parse — fix these errors (only them)", *problems[:20]]))
        problems = parse_errors(step, engine)
        if problems:
            step.task(ctx, "edit", f"RTL(F) still does not parse: {problems[0]}", "failed")
            raise StepFailed("RTL(F) does not parse: " + "; ".join(problems[:5]))
        fixed = " (one more round for parse errors)"
    step.task(ctx, "edit", f"{len(out.changes)} file(s) changed{fixed}: {out.summary}")
    return out
