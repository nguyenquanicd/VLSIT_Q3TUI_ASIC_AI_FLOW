"""Task `check` of eco_patch: the edits are netlist edits and queries only (`tcl.check_edits`: they run in dc_shell) and fit the ORG netlist
(`tcl.check_structure`) — checked as the edits are made (`edits.checked` / `edits.write_edits`: refused edits go back to the LLM once);
then `eco/patch/eco_patch.tcl` is written (the old one backed up), and the timing fixes made for the old patch are dropped."""
from __future__ import annotations

from q3tui.flows.eco.lib import tcl
from q3tui.flows.eco.lib.models import NetlistEdits
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("check", "netlist edits and queries only; every cell, net and instance fits the netlist")


def run(step, ctx: StepContext, out: NetlistEdits) -> None:
    engine, project = ctx.engine, ctx.project
    net, patch = step.org_netlist(engine), step.patch_file(engine)
    step.task(ctx, "check", "netlist edits only; they fit the netlist")
    patch.parent.mkdir(parents=True, exist_ok=True)
    edit_lines = lambda lines: [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]  # noqa: E731
    if ctx.feedback and patch.is_file() and edit_lines(patch.read_text().splitlines()) == edit_lines(out.commands):
        # (the same edits: nothing downstream would change, the fix loop would stall on the old result)
        raise StepFailed(f"the revised patch has the same edits as {project.rel(patch)}: fix it by hand or give eco_patch another hint")
    if patch.is_file():
        project.backup([patch])
    notes = "".join(f"# {ln}\n" for ln in out.notes.splitlines() if ln.strip())
    patch.write_text(tcl.edits_text(out.commands, f"eco_patch on {project.rel(net)}") + ("#\n" + notes if notes else ""))
    old_fixes = step.sta_fixes(engine)  # (timing fixes were made for the netlist of the old patch: eco_sta looks again)
    if old_fixes:
        project.backup(old_fixes)
        for f in old_fixes:
            f.unlink()
        ctx.emit("log", message=f"patch changed: {len(old_fixes)} earlier timing fix(es) dropped (backed up)")
