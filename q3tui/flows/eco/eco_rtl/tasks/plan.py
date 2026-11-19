"""Task `plan` of eco_rtl (LLM, read-only): the smallest change found in the ORG netlist itself (fewest new cells, existing nets reused, at the
register / output where it acts — no guess of what a new synthesis would make), as Design Compiler netlist edits, and the RTL change that
mirrors them (`schemas/eco_rtl_plan.json`). Code checks the edits against the netlist (`edits.checked`: named from the top, allowed commands,
cells / nets that exist) — refused ones go back to the plan once (only their netlist edits are used: the RTL change stays the first plan's)."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.lib.base import task_prompt
from q3tui.flows.eco.lib.models import RtlPlan
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext

TASK = ("plan", "AI, read-only: the smallest change in the ORG netlist, then the RTL change that mirrors it")
PROMPT = task_prompt(__file__)
PLAN_JSON = "eco_rtl_plan.json"  # schemas/: the plan of the pending change, the request it answers, the decision


def edits_text(rtl_edits: list[dict]) -> str:
    """The plan's exact RTL edits, for a person or an LLM that makes them."""
    return "\n".join(f"In {e['file']} replace:\n{e['old']}\nwith:\n{e['new']}" for e in rtl_edits)


def denied(step, engine) -> list[Path]:
    project, eco = engine.project, step.eco_dir(engine)
    return [project.build_dir, step.org_dir(engine), eco / "org", eco / "netlist", eco / "patch", project.src_dir / "tb", project.tb_dir]


def spec_part(step, engine) -> list[str]:
    """Project mode: the spec update the RTL follows (eco_spec), as a diff against the ORG spec."""
    d = step.spec_diff(engine)
    if step.mode(engine) != "project" or not d.is_file() or not d.read_text().strip():
        return []
    return [f"## The spec update of this ECO ({engine.project.rel(d)}, against the ORG spec in ref/)", d.read_text(errors="replace"), ""]


async def run(step, ctx: StepContext, key: dict, feedback: list[str], update: bool, req: Path, mapping: dict, qkey: str) -> dict:
    """The plan of the change (PLAN_JSON, kept until the change is made: a run again with the same request reuses it)."""
    engine, project = ctx.engine, ctx.project
    pending = step.read(engine, PLAN_JSON, {}) or {}
    if pending.get("qkey") != qkey or ctx.regenerate:  # (regenerate: plan again, never the kept plan)
        from q3tui.flows.eco.lib import edits, tcl
        net = step.org_netlist(engine)
        task = [f"## The requirement ({project.rel(req)})", req.read_text(errors="replace"), "", *spec_part(step, engine),
                f"## The RTL to change (top `{step.top(engine)}`; " + ("the current RTL(F)" if update else "copies of the ORG RTL") + ")",
                *[f"- {f}" for f in mapping], "",
                f"## The ORG netlist: {project.rel(net)} (Grep it for the registers, ports and nets the change touches; never read it whole)",
                edits.cells_block(net, step.libraries(engine))]
        if update:
            task += ["", "## Change requests on this RTL(F)", *[f"- {x}" for x in feedback],
                     f"(The changes made so far against the ORG RTL: {project.rel(step.rtl_diff(engine))}.)"]
        stage = Stage(name="eco_rtl_plan", system_prompt=PROMPT, prompt="\n".join(task), cwd=project.root,
                      builtin_tools=["Read", "Grep", "Glob"], output_model=RtlPlan,
                      deny_dirs=[d for d in denied(step, engine) if d != net.parent])  # (the plan reads the ORG netlist)
        plan: RtlPlan = (await ctx.llm(stage)).output
        cmds, problems = edits.checked(ctx, plan.netlist_edits, net, step.libraries(engine)) if plan.netlist_edits else ([], [])
        if problems:  # (refused: back to the plan once, with what is wrong — before the RTL, dv and Sanity run on it)
            stage = Stage(name="eco_rtl_plan", system_prompt=PROMPT, cwd=project.root, builtin_tools=["Read", "Grep", "Glob"],
                          output_model=RtlPlan, deny_dirs=stage.deny_dirs,
                          prompt=stage.prompt + "\n\n## Your netlist edits were refused — fix these problems (only `netlist_edits` is used from this answer: "
                          "the RTL change stays the one below)\n"
                          + "\n".join(f"- {p}" for p in problems) + "\n\nPrevious netlist edits:\n" + "\n".join(cmds)
                          + "\n\nThe RTL change they must mirror:\n" + edits_text([e.model_dump() for e in plan.rtl_edits]))
            retry: RtlPlan = (await ctx.llm(stage)).output  # (only its netlist edits: the RTL change stays the first plan's, word for word)
            plan = plan.model_copy(update={"netlist_edits": retry.netlist_edits})
            cmds, problems = edits.checked(ctx, plan.netlist_edits, net, step.libraries(engine)) if plan.netlist_edits else ([], [])
        pending = {"qkey": qkey, "key": key, "feedback": feedback, **plan.model_dump(), "netlist_edits": cmds,
                   "edit_problems": problems, **({k: tcl.netlist_cost(cmds)[k] for k in ("new_cells", "net_cells")} if cmds and not problems
                                                 else {"new_cells": None})}
        step.write(engine, PLAN_JSON, pending)
    n_edits, refused = len(pending.get("netlist_edits") or []), pending.get("edit_problems") or []
    step.task(ctx, "plan", (f"netlist: {pending.get('new_cells')} new cell(s)"
                            + (f" (cell count {pending['net_cells']:+d})" if pending.get("net_cells", pending.get("new_cells")) != pending.get("new_cells") else "")
                            + f", {n_edits} edit(s), checked: {pending.get('netlist_impact', '')}"
                            if n_edits and not refused else
                            f"netlist: the planned edits are refused ({'; '.join(refused[:2])}): eco_patch writes them"
                            if refused else "netlist: no edits planned")
              + f" — RTL: {pending['plan']}")
    if refused:
        ctx.emit("warning", message=f"RTL plan: its netlist edits are refused ({refused[0]}): eco_patch writes the patch")
    return pending
