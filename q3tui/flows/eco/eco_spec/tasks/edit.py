"""Task `edit` of eco_spec: a spec that is your own (not the spec flow's): an LLM stage (prompt `edit.md`) edits the spec documents in place
(only spec/, never the intent)."""
from __future__ import annotations

from q3tui.flows.eco.eco_spec.tasks.request import Request
from q3tui.flows.eco.lib.base import task_prompt
from q3tui.flows.eco.lib.models import RtlUpdate
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext

TASK = ("edit", "a spec that is your own: the AI edits the spec documents itself")
PROMPT = task_prompt(__file__)


async def run(step, ctx: StepContext, r: Request) -> RtlUpdate:
    """The LLM edits the spec documents itself (a spec that is your own)."""
    engine, project = ctx.engine, ctx.project
    task = [f"## The requirement ({project.rel(r.req)})", r.req.read_text(errors="replace"), "",
            "## The spec documents: edit them in place (the ORG spec is kept in " + project.rel(r.refs[0].parent) + ")",
            *[f"- {project.rel(d)}" for d in r.docs]]
    if r.update:
        task += ["", "## Change requests on the updated spec", *[f"- {x}" for x in r.feedback],
                 f"(The changes made so far against the ORG spec: {project.rel(step.spec_diff(engine))}.)"]
    stage = Stage(name="eco_spec", system_prompt=PROMPT, prompt="\n".join(task), cwd=project.root,
                  builtin_tools=["Read", "Grep", "Glob", "Edit"], output_model=RtlUpdate, write_dirs=[project.spec_dir],
                  deny_dirs=[project.build_dir, project.src_dir, step.eco_dir(engine) / "netlist", step.eco_dir(engine) / "patch",
                             step.org_dir(engine)])
    intent = project.spec_dir / "intent.md"
    before = intent.read_bytes() if intent.is_file() else None
    out: RtlUpdate = (await ctx.llm(stage)).output
    if intent.is_file() and before is not None and intent.read_bytes() != before:
        intent.write_bytes(before)  # (the intent is yours: the ECO updates the spec documents only)
        ctx.emit("warning", message="spec update: spec/intent.md was edited — put back as it was")
    step.task(ctx, "edit", f"{out.summary} ({len(out.changes)} document(s))")
    return out
