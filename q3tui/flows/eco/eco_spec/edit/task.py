"""Task `edit` of eco_spec: an LLM stage edits the spec documents in place to the requirement (only spec/, never the intent: an edited
intent is put back)."""
from __future__ import annotations

from q3tui.flows.eco.lib.base import task_prompt
from q3tui.flows.eco.lib.models import RtlUpdate
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext

TASK = ("edit", "AI: the spec documents edited in place to the requirement (the smallest change; never the intent)")
PROMPT = task_prompt(__file__)


async def run(step, ctx: StepContext, s) -> RtlUpdate:
    engine, project = ctx.engine, ctx.project
    task = [f"## The requirement ({project.rel(s.req)})", s.req.read_text(errors="replace"), "",
            "## The spec documents: edit them in place (the ORG spec is kept in " + project.rel(s.refs[0].parent) + ")",
            *[f"- {project.rel(d)}" for d in s.docs]]
    if s.update:
        task += ["", "## Change requests on the updated spec", *[f"- {x}" for x in s.feedback],
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
    step.task(ctx, "edit", f"{len(out.changes)} file(s) changed: {out.summary}")
    return out
