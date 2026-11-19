"""ECO step `eco_patch`: PATCH CMD. A read-only LLM stage turns the RTL change (`eco/rtl.diff`, RTL(F), the ORG RTL) into Design Compiler
netlist edits on the ORG netlist; code checks them (`tcl.check_edits`: netlist edits and queries only — they run in dc_shell) and writes
`eco/patch/eco_patch.tcl`. A change request (your review, eco_apply's Design Compiler errors, EQ(2)) revises the current patch.
Its tasks (one folder each): edits, check."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_patch.check import task as check
from q3tui.flows.eco.eco_patch.edits import task as edits
from q3tui.flows.eco.lib.base import PATCH_JSON, RTL_JSON, VERIFY_JSON, EcoStep
from q3tui.pipeline.base import StepContext


class Step(EcoStep):
    name = "eco_patch"
    title = "PATCH CMD: netlist edits for the RTL change"
    deps = ("eco_verify",)
    tasks = (edits.TASK, check.TASK)

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
        check.run(self, ctx, await edits.run(self, ctx))
