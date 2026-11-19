"""Task `edits` of eco_patch: a read-only LLM stage turns the RTL change (`eco/rtl.diff`, RTL(F), the ORG RTL) into Design Compiler netlist
edits on the ORG netlist (prompt.md); `lib/edits.write_edits` checks its answer and sends it back once with the problems. A change request
(your review, eco_apply's Design Compiler errors, EQ(2)) revises the current patch."""
from __future__ import annotations

from q3tui.flows.eco.lib import edits
from q3tui.flows.eco.lib.base import RTL_JSON, task_prompt
from q3tui.flows.eco.lib.models import NetlistEdits
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("edits", "AI (read-only) writes the Design Compiler netlist edits for the RTL change (eco/rtl.diff) on the ORG netlist")
PROMPT = task_prompt(__file__)


async def run(step, ctx: StepContext) -> NetlistEdits:
    engine, project = ctx.engine, ctx.project
    net, patch = step.org_netlist(engine), step.patch_file(engine)
    rtl = step.read(engine, RTL_JSON, {}) or {}
    diff = step.rtl_diff(engine).read_text(errors="replace")
    task = [f"## The RTL change (unified diff ORG → RTL(F), {project.rel(step.rtl_diff(engine))})",
            diff if len(diff) < 40_000 else f"(large: read {project.rel(step.rtl_diff(engine))})", "",
            f"What it does: {rtl.get('summary', '')}", "",
            f"## The ORG netlist to edit: {project.rel(net)} (top `{step.top(engine)}`; Grep it for the cells, nets and pins you touch)",
            edits.cells_block(net), "",
            "## RTL files", *[f"- RTL(F) {f} (ORG {o})" for f, o in (rtl.get("map") or {}).items()]]
    revise = bool(ctx.feedback and patch.is_file() and not ctx.regenerate)
    if revise:
        task += ["", f"## Revise the current patch ({project.rel(patch)}) for these change requests", *[f"- {x}" for x in ctx.feedback]]
    eco = step.eco_dir(engine)
    try:
        out = await edits.write_edits(step, ctx, "eco_patch", PROMPT, "\n".join(task),
                                      [project.build_dir, eco / "netlist", project.src_dir / "tb", project.tb_dir], netlist=net)
    except StepFailed as e:
        step.task(ctx, "edits", "the AI's edits were refused twice", "failed")
        step.task(ctx, "check", str(e), "failed")
        raise
    n = len([c for c in out.commands if c.strip()])
    step.task(ctx, "edits", f"{n} command(s) (AI" + (f", revising the patch for {len(ctx.feedback)} change request(s))" if revise else ")"))
    return out
