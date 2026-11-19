"""Task `edits` of eco_patch: the netlist edits eco_rtl's plan found (and checked) for the RTL change are the patch when they still check;
otherwise — none planned, or a change request (your review, eco_apply's Design Compiler errors, EQ(2)) — a read-only LLM stage (prompt:
`edits.md`) turns the RTL change (`eco/rtl.diff`, RTL(F), the ORG RTL; the planned edits as its start) into Design Compiler netlist edits on
the ORG netlist. A change request revises the current patch."""
from __future__ import annotations

from q3tui.flows.eco.lib import edits
from q3tui.flows.eco.lib.base import RTL_JSON, task_prompt
from q3tui.flows.eco.lib.models import NetlistEdits
from q3tui.pipeline.base import StepContext

TASK = ("edits", "the plan's netlist edits (eco_rtl), or AI, read-only: the RTL change as Design Compiler netlist edits")
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
            edits.cells_block(net, step.libraries(engine)), "",
            "## RTL files", *[f"- RTL(F) {f} (ORG {o})" for f, o in (rtl.get("map") or {}).items()]]
    planned = list(rtl.get("netlist_edits") or [])
    revise = bool(ctx.feedback) and patch.is_file() and not ctx.regenerate
    if planned:  # (eco_rtl found them in this netlist, checked them; the RTL change mirrors them)
        task += ["", f"## The netlist edits planned with the RTL change ({rtl.get('planned_cells', '?')} new cell(s)): start from them",
                 *planned]
    if revise:
        task += ["", f"## Revise the current patch ({project.rel(patch)}) for these change requests", *[f"- {x}" for x in ctx.feedback]]
    eco = step.eco_dir(engine)
    commands, problems = edits.checked(ctx, planned, net, step.libraries(engine)) if planned and not revise else ([], ["-"])
    if not problems:  # (the plan's edits are the patch: no AI writes them again)
        out = NetlistEdits(commands=commands, notes="The netlist edits planned with the RTL change (eco_rtl), checked against the ORG netlist.")
        step.task(ctx, "edits", f"{len(out.commands)} command(s), the plan's (eco_rtl)")
    else:
        out = await edits.write_edits(step, ctx, "eco_patch", PROMPT, "\n".join(task),
                                      [project.build_dir, eco / "netlist", project.src_dir / "tb", project.tb_dir], netlist=net)
        step.task(ctx, "edits", f"{len(out.commands)} command(s)" + (" (AI, from the plan's)" if planned else " (AI)"))
    return out
