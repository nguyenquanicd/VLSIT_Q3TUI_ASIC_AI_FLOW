"""ECO step `eco_patch`: PATCH CMD. A read-only LLM stage turns the RTL change (`eco/rtl.diff`, RTL(F), the ORG RTL) into Design Compiler
netlist edits on the ORG netlist; code checks them (`tcl.check_edits`: netlist edits and queries only — they run in dc_shell) and writes
`eco/patch/eco_patch.tcl`. A change request (your review, eco_apply's Design Compiler errors, EQ(2)) revises the current patch."""
from __future__ import annotations

from pathlib import Path

from q3tui.core.project import sha256_file
from q3tui.flows import skill_sections
from q3tui.flows.eco.lib import edits, tcl
from q3tui.flows.eco.lib.base import PATCH_JSON, RTL_JSON, VERIFY_JSON, EcoStep
from q3tui.pipeline.base import StepContext, StepFailed

SYSTEM = skill_sections(Path(__file__).parent / "md" / "skill.md")


class Step(EcoStep):
    name = "eco_patch"
    title = "PATCH CMD: netlist edits for the RTL change"
    deps = ("eco_verify",)

    def inputs(self, engine) -> list[Path]:
        return [self.artifact(engine, RTL_JSON), self.rtl_diff(engine), self.org_netlist(engine), self.artifact(engine, VERIFY_JSON)]

    def outputs(self, engine) -> list[Path]:
        return [f for f in (self.artifact(engine, PATCH_JSON), self.patch_file(engine)) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return self.outputs(engine)

    def missing_input(self, engine) -> str | None:
        if not self.rtl_diff(engine).is_file() or not self.artifact(engine, RTL_JSON).is_file():
            return "RTL(F) is needed first (step eco_rtl)"
        status = (self.read(engine, VERIFY_JSON, {}) or {}).get("status")
        if status not in ("passed", "skipped"):
            return f"dv + Sanity on the ECO'd design first (step eco_verify: {status or 'not run'})"
        return None

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        net, patch = self.org_netlist(engine), self.patch_file(engine)
        rtl = self.read(engine, RTL_JSON, {}) or {}
        diff = self.rtl_diff(engine).read_text(errors="replace")
        task = [f"## The RTL change (unified diff ORG → RTL(F), {project.rel(self.rtl_diff(engine))})",
                diff if len(diff) < 40_000 else f"(large: read {project.rel(self.rtl_diff(engine))})", "",
                f"What it does: {rtl.get('summary', '')}", "",
                f"## The ORG netlist to edit: {project.rel(net)} (top `{self.top(engine)}`; Grep it for the cells, nets and pins you touch)",
                edits.cells_block(net), "",
                "## RTL files", *[f"- RTL(F) {f} (ORG {o})" for f, o in (rtl.get("map") or {}).items()]]
        if ctx.feedback and patch.is_file() and not ctx.regenerate:
            task += ["", f"## Revise the current patch ({project.rel(patch)}) for these change requests", *[f"- {x}" for x in ctx.feedback]]
        eco = self.eco_dir(engine)
        out = await edits.write_edits(self, ctx, "eco_patch", SYSTEM["PATCH"], "\n".join(task),
                                      [project.build_dir, eco / "netlist", project.src_dir / "tb", project.tb_dir], netlist=net)
        patch.parent.mkdir(parents=True, exist_ok=True)
        edit_lines = lambda lines: [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]  # noqa: E731
        if ctx.feedback and patch.is_file() and edit_lines(patch.read_text().splitlines()) == edit_lines(out.commands):
            # (the same edits: nothing downstream would change, the fix loop would stall on the old result)
            raise StepFailed(f"the revised patch has the same edits as {project.rel(patch)}: fix it by hand or give eco_patch another hint")
        if patch.is_file():
            project.backup([patch])
        notes = "".join(f"# {ln}\n" for ln in out.notes.splitlines() if ln.strip())
        patch.write_text(tcl.edits_text(out.commands, f"eco_patch on {project.rel(net)}") + ("#\n" + notes if notes else ""))
        old_fixes = self.sta_fixes(engine)  # (timing fixes were made for the netlist of the old patch: eco_sta looks again)
        if old_fixes:
            project.backup(old_fixes)
            for f in old_fixes:
                f.unlink()
            ctx.emit("log", message=f"patch changed: {len(old_fixes)} earlier timing fix(es) dropped (backed up)")
        self.write(engine, PATCH_JSON, {"commands": len([c for c in out.commands if c.strip()]), "notes": out.notes,
                                        "netlist_sha256": sha256_file(net), "file": project.rel(patch)})
        ctx.emit("log", message=f"patch: {len(out.commands)} netlist edit(s) in {project.rel(patch)}")
