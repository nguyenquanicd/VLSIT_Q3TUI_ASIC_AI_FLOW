"""ECO step `eco_apply`: Design Compiler (tool role `asic_synth`) reads the ORG netlist, links it, sources the patch and then the timing fixes
of eco_sta in order, and writes the Post NETLIST (`eco/netlist/<top>.v`) — no compile: the netlist changes only where the edits say. Errors of
the patch go back to eco_patch (the fix loop, bounded); an error of a timing fix removes that fix and fails the step. Its task, in `tasks/`: dc."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_apply.tasks import dc
from q3tui.flows.eco.lib.base import APPLY_JSON, PATCH_JSON, EcoStep
from q3tui.pipeline.base import StepContext


class Step(EcoStep):
    name = "eco_apply"
    title = "Post NETLIST: the patch applied (Design Compiler)"
    deps = ("eco_patch",)
    tasks = (dc.TASK,)
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
        await dc.run(self, ctx)
