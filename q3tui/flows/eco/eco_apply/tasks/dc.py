"""Task `dc` of eco_apply: Design Compiler (tool role `asic_synth`) reads the ORG netlist, links it, sources the patch and then the timing
fixes of eco_sta in order, and writes the Post NETLIST — no compile. Errors of the patch go back to eco_patch (the fix loop, bounded); an
error of a timing fix removes that fix and fails the step."""
from __future__ import annotations

import shutil

from q3tui.core.project import sha256_file
from q3tui.flows.eco.lib import tcl
from q3tui.flows.eco.lib.base import APPLY_JSON
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("dc", "Design Compiler: read the ORG netlist, source the patch (+ timing fixes), write the Post NETLIST — no compile; "
              "its error lines back to eco_patch (the fix loop)")


async def run(step, ctx: StepContext) -> None:
    engine, project = ctx.engine, ctx.project
    top, libs = step.top(engine), step.need_libraries(engine)
    tools = await step.need_tool(engine, "asic_synth", "module synopsys/syn")
    work, post, patch = step.build_dir(engine), step.post_netlist(engine), step.patch_file(engine)
    fixes = step.sta_fixes(engine)
    prev = step.read(engine, APPLY_JSON, {}) or {}
    post.unlink(missing_ok=True)
    script = work / "apply.tcl"
    script.write_text(tcl.apply_script(libs, step.org_netlist(engine), top, [patch, *fixes], post, work))
    ctx.emit("log", message=f"applying {project.rel(patch)}" + (f" + {len(fixes)} timing fix(es)" if fixes else "") + " to the ORG netlist…")
    step.top_name = top
    res, log = await step.run_tool(tools, "asic_synth", script, work, "dc_apply.log")
    rep = step.reports_dir(engine)
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "apply_dc.log").write_text(log)
    if (work / "check_design.rpt").is_file():
        shutil.copyfile(work / "check_design.rpt", rep / "apply_check_design.rpt")
    errors = tcl.apply_errors(log)
    done = "Q3TUI_ECO_APPLY: DONE" in log and post.is_file() and not errors
    what = f"{len(errors)} error(s)" + (f" + {len(fixes)} timing fix(es)" if fixes else "")
    patch_sha = sha256_file(patch)
    if done:
        step.write(engine, APPLY_JSON, {"status": "pass", "patch_sha256": patch_sha, "fixes": [project.rel(f) for f in fixes],
                                        "netlist": project.rel(post), "log": project.rel(rep / "apply_dc.log")})
        ctx.emit("log", message=f"Post NETLIST: {project.rel(post)}")
        step.task(ctx, "dc", f"{what}: Post NETLIST {project.rel(post)}")
        step.reset_rounds(ctx)
        return
    post.unlink(missing_ok=True)
    if not errors:
        step.task(ctx, "dc", "no Post NETLIST written", "failed")
        from q3tui.eda import tools as toolmod
        toolmod.check_broken(res, "asic_synth")
        raise StepFailed(f"Design Compiler wrote no Post NETLIST (log: {project.rel(rep / 'apply_dc.log')})")
    step.write(engine, APPLY_JSON, {"status": "failed", "errors": errors, "patch_sha256": patch_sha, "log": project.rel(rep / "apply_dc.log")})
    if fixes and prev.get("status") == "pass" and prev.get("patch_sha256") == patch_sha:  # the patch applied before: the new timing fix fails
        bad = fixes[-1]
        project.backup([bad])
        bad.unlink()
        step.task(ctx, "dc", f"{what}: the timing fix {project.rel(bad)} does not apply (removed)", "failed")
        raise StepFailed(f"the timing fix {project.rel(bad)} does not apply (removed; run eco_sta again for another): {errors[0]}")
    meta, n = step.rounds(ctx)
    if n >= step.round_limit(ctx):
        step.reset_rounds(ctx)
        step.task(ctx, "dc", f"{what}: the patch still does not apply after {n} round(s)", "failed")
        raise StepFailed(f"the patch still does not apply after {n} round(s) with eco_patch: {errors[0]} (log: {project.rel(rep / 'apply_dc.log')})")
    step.hand_back(ctx, "eco_patch", "From eco_apply: Design Compiler refused the patch on the ORG netlist. Its error lines:\n" + "\n".join(errors))
    step.task(ctx, "dc", f"{what}: refused → eco_patch (round {n + 1}): {errors[0]}", "handed")
    ctx.emit("warning", message=f"the patch does not apply → eco_patch (round {n + 1}): {errors[0]}")
