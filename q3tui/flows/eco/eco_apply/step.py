"""ECO step `eco_apply`: Design Compiler (tool role `asic_synth`) reads the ORG netlist, links it, sources the patch and then the timing fixes
of eco_sta in order, and writes the Post NETLIST (`eco/netlist/<top>.v`) — no compile: the netlist changes only where the edits say. Errors of
the patch go back to eco_patch (the fix loop, bounded); an error of a timing fix removes that fix and fails the step."""
from __future__ import annotations

import shutil
from pathlib import Path

from q3tui.core.project import sha256_file
from q3tui.flows.eco.lib import tcl
from q3tui.flows.eco.lib.base import APPLY_JSON, PATCH_JSON, EcoStep
from q3tui.pipeline.base import StepContext, StepFailed


class Step(EcoStep):
    name = "eco_apply"
    title = "Post NETLIST: the patch applied (Design Compiler)"
    deps = ("eco_patch",)
    tool_roles = ("asic_synth",)

    def inputs(self, engine) -> list[Path]:
        return [self.org_netlist(engine), self.patch_file(engine), *self.sta_fixes(engine)]

    def outputs(self, engine) -> list[Path]:
        return [f for f in (self.artifact(engine, APPLY_JSON), self.post_netlist(engine)) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return self.outputs(engine)

    def missing_input(self, engine) -> str | None:
        if not self.patch_file(engine).is_file() or not self.artifact(engine, PATCH_JSON).is_file():
            return "the patch is needed first (step eco_patch)"
        return None

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        top, libs = self.top(engine), self.need_libraries(engine)
        tools = await self.need_tool(engine, "asic_synth", "module synopsys/syn")
        work, post, patch = self.build_dir(engine), self.post_netlist(engine), self.patch_file(engine)
        fixes = self.sta_fixes(engine)
        prev = self.read(engine, APPLY_JSON, {}) or {}
        post.unlink(missing_ok=True)
        script = work / "apply.tcl"
        script.write_text(tcl.apply_script(libs, self.org_netlist(engine), top, [patch, *fixes], post, work))
        ctx.emit("log", message=f"applying {project.rel(patch)}" + (f" + {len(fixes)} timing fix(es)" if fixes else "") + " to the ORG netlist…")
        self.top_name = top
        res, log = await self.run_tool(tools, "asic_synth", script, work, "dc_apply.log")
        rep = self.reports_dir(engine)
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "apply_dc.log").write_text(log)
        if (work / "check_design.rpt").is_file():
            shutil.copyfile(work / "check_design.rpt", rep / "apply_check_design.rpt")
        errors = tcl.apply_errors(log)
        done = "Q3TUI_ECO_APPLY: DONE" in log and post.is_file() and not errors
        patch_sha = sha256_file(patch)
        if done:
            self.write(engine, APPLY_JSON, {"status": "pass", "patch_sha256": patch_sha, "fixes": [project.rel(f) for f in fixes],
                                            "netlist": project.rel(post), "log": project.rel(rep / "apply_dc.log")})
            ctx.emit("log", message=f"Post NETLIST: {project.rel(post)}")
            self.reset_rounds(ctx)
            return
        post.unlink(missing_ok=True)
        if not errors:
            from q3tui.eda import tools as toolmod
            toolmod.check_broken(res, "asic_synth")
            raise StepFailed(f"Design Compiler wrote no Post NETLIST (log: {project.rel(rep / 'apply_dc.log')})")
        self.write(engine, APPLY_JSON, {"status": "failed", "errors": errors, "patch_sha256": patch_sha, "log": project.rel(rep / "apply_dc.log")})
        if fixes and prev.get("status") == "pass" and prev.get("patch_sha256") == patch_sha:  # the patch applied before: the new timing fix fails
            bad = fixes[-1]
            project.backup([bad])
            bad.unlink()
            raise StepFailed(f"the timing fix {project.rel(bad)} does not apply (removed; run eco_sta again for another): {errors[0]}")
        meta, n = self.rounds(ctx)
        if n >= self.round_limit(ctx):
            self.reset_rounds(ctx)
            raise StepFailed(f"the patch still does not apply after {n} round(s) with eco_patch: {errors[0]} (log: {project.rel(rep / 'apply_dc.log')})")
        self.hand_back(ctx, "eco_patch", "From eco_apply: Design Compiler refused the patch on the ORG netlist. Its error lines:\n" + "\n".join(errors))
        ctx.emit("warning", message=f"the patch does not apply → eco_patch (round {n + 1}): {errors[0]}")
