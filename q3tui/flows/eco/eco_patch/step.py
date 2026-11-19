"""ECO step `eco_patch`: PATCH CMD. The netlist edits eco_rtl's plan found (and checked) for the RTL change are the patch when they still
check; otherwise — none planned, or a change request (your review, eco_apply's Design Compiler errors, EQ(2)) — a read-only LLM stage turns
the RTL change (`eco/rtl.diff`, RTL(F), the ORG RTL; the planned edits as its start) into Design Compiler netlist edits on the ORG
netlist; code checks them (`tcl.check_edits`: netlist edits and queries only — they run in dc_shell) and writes
`eco/patch/eco_patch.tcl`. A change request (your review, eco_apply's Design Compiler errors, EQ(2)) revises the current patch.

Tasks: edits (LLM), check (the allow-list and the netlist structure; refused edits go back to the LLM once), cost (`tcl.netlist_cost`: the
ECO's first measure). A patch that adds more than `max_new_cells` cells asks you (blocking, once per patch): keep it (recommended;
auto-answer keeps it), or hand eco_rtl a request for an RTL change with a smaller netlist impact — the patch is then dropped (backed up) so
nothing downstream runs on it, and eco_rtl, eco_verify and this step run again (bounded by the fix rounds). The tasks: `tasks/`."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_patch.tasks import check, cost, edits
from q3tui.flows.eco.lib.base import PATCH_JSON, RTL_JSON, VERIFY_JSON, EcoStep
from q3tui.pipeline.base import StepContext


class Step(EcoStep):
    name = "eco_patch"
    title = "PATCH CMD: netlist edits for the RTL change"
    deps = ("eco_verify",)
    tasks = (edits.TASK, check.TASK, cost.TASK)

    def inputs(self, engine) -> list[Path]:
        return [self.artifact(engine, RTL_JSON), self.rtl_diff(engine), self.org_netlist(engine), self.artifact(engine, VERIFY_JSON),
                self._q_paths(engine)[1]]

    def outputs(self, engine) -> list[Path]:
        return [f for f in (self.artifact(engine, PATCH_JSON), self.patch_file(engine)) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *self._q_paths(engine)]

    def missing_input(self, engine) -> str | None:
        if not self.rtl_diff(engine).is_file() or not self.artifact(engine, RTL_JSON).is_file():
            return "RTL(F) is needed first (step eco_rtl)"
        status = (self.read(engine, VERIFY_JSON, {}) or {}).get("status")
        if status not in ("passed", "skipped"):
            return f"dv + Sanity on the ECO'd design first (step eco_verify: {status or 'not run'})"
        return None

    async def run(self, ctx: StepContext) -> None:
        out = await edits.run(self, ctx)
        check.run(self, ctx, out)
        cost.run(self, ctx, out)
