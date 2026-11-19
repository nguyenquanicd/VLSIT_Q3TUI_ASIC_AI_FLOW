"""Task `record` of eco_inputs: `schemas/eco_inputs.json` records the choice, the mode, the ref and the files' hashes."""
from __future__ import annotations

from q3tui.core.project import sha256_file
from q3tui.flows.eco.lib import ref as refmod
from q3tui.flows.eco.lib.base import INPUTS_JSON
from q3tui.pipeline.base import StepContext

TASK = ("record", "schemas/eco_inputs.json: the inputs, the mode, the ref")


def run(step, ctx: StepContext, top: str, paths: dict[str, str], how: str, rec: dict) -> None:
    engine, project = ctx.engine, ctx.project
    root = project.root
    mode, ref = rec["mode"], root / rec["path"]
    rel = {k: (project.rel(root / v) if (root / v).resolve().is_relative_to(root.resolve()) else str(root / v)) for k, v in paths.items()}
    org = ref / "netlist" / f"{top}.v"
    step.write(engine, INPUTS_JSON, {"top": top, "mode": mode, "ref": rec["path"], "source": {k: rel[k] for k in ("rtl", "netlist")},
                                     "rtl": project.rel(ref / refmod.RTL_FILELIST), "netlist": project.rel(org),
                                     "requirement": rel["requirement"], "how": how, "org_netlist": project.rel(org),
                                     "org_sdc": project.rel(org.with_suffix(".sdc")) if org.with_suffix(".sdc").is_file() else None,
                                     "org_svf": project.rel(org.with_suffix(".svf")) if org.with_suffix(".svf").is_file() else None,
                                     "sha256": {k: sha256_file(root / v) for k, v in paths.items()}})
    step.task(ctx, "record", project.rel(step.artifact(engine, INPUTS_JSON)))
    ctx.emit("log", message=f"ECO inputs ({how}, {mode} mode): RTL {rel['rtl']}, netlist {rel['netlist']}, requirement {rel['requirement']}"
                            + ("" if mode == "project" else " — a fire-fighting ECO: no spec update, no dv / Sanity run"))
