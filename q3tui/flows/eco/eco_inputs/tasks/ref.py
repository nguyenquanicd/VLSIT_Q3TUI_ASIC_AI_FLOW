"""Task `ref` of eco_inputs: the ORG design kept in `ref/<name>/` (you are asked the name, ECOREF; lib/ref.py), the netlist with its
`.sdc` / `.svf` in `ref/<name>/netlist/` — or this ECO's ref reused (`eco/ref.json` points to it)."""
from __future__ import annotations

import re
from pathlib import Path

from q3tui.flows.eco.lib import ref as refmod
from q3tui.flows.eco.lib.base import answer_is
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("ref", "the ORG design kept in ref/<name>/ (ECOREF), or this ECO's ref reused")


def name(step, ctx: StepContext, top: str) -> str | None:
    """The folder name of ref/: the `ref_name` option, else your answer (default: the top module); None while it is awaited."""
    if step.options.get("ref_name"):
        return refmod.clean_name(str(step.options["ref_name"]))
    qid, answer = step.decide(ctx, "ref", "ECOREF", (
        f"Where should the ECO keep the ORG design (the un-ECO'd RTL and netlist; for the project's own RTL also spec/, src/, "
        f"constraints/, schemas/)? It goes to ref/<name>/ "
        f"(ref/<name>_DDMMYYYY_HHMMSS when that folder exists already)."),
        [(f"ref/{top} (Recommended)", "named after the top module"), ("My own name: name=<folder>", "answer with the folder name")])
    if answer is None:
        ctx.emit("warning", message=f"ECO ref: answer {qid} (the name of the ref/ folder), then run again")
        return None
    if answer_is(answer, f"ref/{top}", "use the default", "default", "yes", "mặc định") or ("=" in answer and not re.search(r"name\s*[=:]", answer)):
        return top  # (an answer that is not a name, e.g. the paths given to the other question: the default)
    return refmod.clean_name(answer)


def run(step, ctx: StepContext, top: str, mode: str, filelist: Path, netlist: Path) -> dict | None:
    """The ref record (eco/ref.json), new or reused; None while the name is awaited."""
    project = ctx.project
    root = project.root
    rec = refmod.pointer(project)
    if rec and rec.get("sources") == {"rtl": str(filelist), "netlist": str(netlist)} and (root / rec.get("path", "-")).is_dir():
        step.task(ctx, "ref", f"{rec['path']} reused (kept from {rec.get('created')})")
        ctx.emit("log", message=f"ECO ref: {rec['path']} (kept from {rec.get('created')}; delete eco/ref.json to start a new ECO)")
        return rec
    folder = name(step, ctx, top)
    if folder is None:
        step.task(ctx, "ref", "answer the ref name question (ECOREF)", "waiting")
        return None
    from q3tui.hdl.filelist import parse_filelist
    d = refmod.unique_dir(project, folder)
    try:
        rec = refmod.snapshot(project, d, mode, filelist, parse_filelist(filelist, root).files, netlist, top)
    except FileNotFoundError as exc:
        raise StepFailed(str(exc)) from exc
    refmod.save_pointer(project, rec)
    ctx.emit("log", message=f"ECO ref: the ORG design kept in {rec['path']} ({mode} mode)")
    step.task(ctx, "ref", f"the ORG design kept in {rec['path']}")
    return rec
