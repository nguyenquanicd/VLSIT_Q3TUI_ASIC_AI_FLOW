"""Task `check` of eco_patch: the edits were checked (netlist edits and queries only — they run in dc_shell — and they fit the ORG netlist:
`lib/edits.write_edits`); a revision with the same edits as the current patch stops the fix loop; then `eco/patch/eco_patch.tcl` is written
and the timing fixes made for the old patch are dropped."""
from __future__ import annotations

from q3tui.core.project import sha256_file
from q3tui.flows.eco.lib import tcl
from q3tui.flows.eco.lib.base import PATCH_JSON
from q3tui.flows.eco.lib.models import NetlistEdits
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("check", "netlist edits only, fitting the ORG netlist (refused edits go back to the AI once); writes eco/patch/eco_patch.tcl")


def run(step, ctx: StepContext, out: NetlistEdits) -> None:
    engine, project = ctx.engine, ctx.project
    net, patch = step.org_netlist(engine), step.patch_file(engine)
    patch.parent.mkdir(parents=True, exist_ok=True)
    edit_lines = lambda lines: [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]  # noqa: E731
    if ctx.feedback and patch.is_file() and edit_lines(patch.read_text().splitlines()) == edit_lines(out.commands):
        # (the same edits: nothing downstream would change, the fix loop would stall on the old result)
        step.task(ctx, "check", "the revised patch has the same edits as the current one", "failed")
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
    step.write(engine, PATCH_JSON, {"commands": len([c for c in out.commands if c.strip()]), "notes": out.notes,
                                    "netlist_sha256": sha256_file(net), "file": project.rel(patch)})
    step.task(ctx, "check", f"netlist edits only; they fit the netlist → {project.rel(patch)}"
              + (f" ({len(old_fixes)} old timing fix(es) dropped)" if old_fixes else ""))
    ctx.emit("log", message=f"patch: {len(out.commands)} netlist edit(s) in {project.rel(patch)}")
