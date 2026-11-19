"""Task `cost` of eco_patch: the patch measured in the netlist (`tcl.netlist_cost`: the ECO's first measure, `schemas/eco_patch.json`). A
patch that adds more than `max_new_cells` cells asks you (blocking, once per patch): keep it (recommended; auto-answer keeps it), or hand
eco_rtl a request for an RTL change with a smaller netlist impact — the patch is then dropped (backed up) so nothing downstream runs on it,
and eco_rtl, eco_verify and eco_patch run again (bounded by the fix rounds)."""
from __future__ import annotations

from q3tui.core.project import sha256_file, sha256_json
from q3tui.flows.eco.lib import tcl
from q3tui.flows.eco.lib.base import PATCH_JSON, RTL_JSON, answer_is
from q3tui.flows.eco.lib.models import NetlistEdits
from q3tui.pipeline.base import StepContext

TASK = ("cost", "the patch in the netlist: new cells, nets, connections; over max_new_cells: keep it or ask eco_rtl for a cheaper change")
KEEP_PATCH, CHEAPER = "Keep this patch", "Look for a cheaper RTL change"


def run(step, ctx: StepContext, out: NetlistEdits) -> None:
    engine, project = ctx.engine, ctx.project
    net, patch = step.org_netlist(engine), step.patch_file(engine)
    cost = tcl.netlist_cost(out.commands)
    record = {**cost, "notes": out.notes, "netlist_sha256": sha256_file(net), "file": project.rel(patch)}
    step.write(engine, PATCH_JSON, record)
    ctx.emit("log", message=f"patch: {len(out.commands)} netlist edit(s) in {project.rel(patch)}")
    _judge(step, ctx, out.commands, cost, record)


def _judge(step, ctx: StepContext, commands: list[str], cost: dict, record: dict) -> None:
    """Over `max_new_cells`: your choice (once per patch) — keep it, or a request to eco_rtl for a cheaper RTL change (the patch dropped)."""
    engine, project = ctx.engine, ctx.project
    limit = int(step.options.get("max_new_cells", 10))
    planned = (step.read(engine, RTL_JSON, {}) or {}).get("planned_cells")
    what = (f"{cost['new_cells']} new cell(s) ({', '.join(f'{n}× {t}' for t, n in cost['cell_types'].items()) or 'buffers'}"
            + (f"; planned {planned}" if planned is not None else "") + ")"
            + (f", {cost['removed']} removed (cell count {cost['net_cells']:+d})" if cost.get("removed") else "") + ", "
            f"{cost['new_nets']} new net(s), {cost['connects']} connect / {cost['disconnects']} disconnect, {cost['commands']} command(s)")
    _, n = step.rounds(ctx)
    if cost["new_cells"] <= limit or n >= step.round_limit(ctx):
        step.task(ctx, "cost", what + (f" (over max_new_cells {limit}, the fix rounds are used up)" if cost["new_cells"] > limit else ""))
        if cost["new_cells"] <= limit:
            step.reset_rounds(ctx)
        return
    key = sha256_json([commands, sha256_file(step.rtl_diff(engine))])[:16]  # (a new RTL(F) asks again, even for the same edits)
    qid, answer = step.decide(ctx, f"cost:{key}", "ECOPATCH", (
        f"PATCH CMD: the patch adds {what} — more than max_new_cells ({limit}). Keep it, or have eco_rtl look for an RTL change with a "
        f"smaller netlist impact (then dv / Sanity and this step run again)?"),
        [(KEEP_PATCH + " (Recommended)", "the patch goes on to Design Compiler as it is"),
         (f"{CHEAPER}: <a hint, or leave it>", "eco_rtl plans again for fewer netlist edits; your words go with the request")])
    if answer is None:
        step.task(ctx, "cost", f"{what}: answer {qid}", "waiting")
        ctx.emit("warning", message=f"PATCH CMD: {cost['new_cells']} new cells (max_new_cells {limit}) — answer {qid}")
        return
    if answer_is(answer, KEEP_PATCH, "keep"):
        step.task(ctx, "cost", f"{what}; kept ({qid or 'auto-answer'})")
        return
    hint = answer.strip()
    hint = hint[len(CHEAPER):].lstrip(" :-").strip() if answer_is(hint, CHEAPER) else hint
    hint = "" if hint.startswith("<") else hint
    step.hand_back(ctx, "eco_rtl", f"From eco_patch: the netlist patch for the current RTL(F) costs {what} (max_new_cells {limit}; "
                                   f"{project.rel(step.patch_file(engine))}). Plan an RTL change with a smaller netlist impact for the same "
                                   f"requirement" + (f": {hint}" if hint else "") + ".")
    project.backup([step.patch_file(engine)])
    step.patch_file(engine).unlink()  # (nothing downstream runs on a patch you sent back)
    step.write(engine, PATCH_JSON, {**record, "status": "handed", "question": qid})
    step.task(ctx, "cost", f"{what}; sent back to eco_rtl for a cheaper change ({qid})", "handed")
