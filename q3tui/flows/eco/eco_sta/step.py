"""ECO step `eco_sta`: STA of the Post NETLIST with PrimeTime (tool role `eco_sta`): setup and hold paths, all violators, the global summary
(`eco/reports/sta_*.rpt`, `eco/reports/sta.md`). Only setup fails the step (before placement a hold violation is reported, not fixed). A setup
violation gets a timing fix: a read-only LLM stage writes netlist edits (sizing, buffering; checked like the patch) to
`eco/patch/sta_fix_<n>.tcl`, eco_apply applies them after the patch, then EQ(2) and this step run again — bounded by `max_rounds`.
Its tasks (one folder each): primetime, fix."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_sta.fix import task as fix
from q3tui.flows.eco.eco_sta.primetime import task as primetime
from q3tui.flows.eco.eco_sta.primetime.task import REPORTS
from q3tui.flows.eco.lib.base import EQ2_JSON, STA_JSON, EcoStep
from q3tui.pipeline.base import StepContext


class Step(EcoStep):
    name = "eco_sta"
    title = "STA of the Post NETLIST (PrimeTime)"
    deps = ("eco_eq2",)
    tasks = (primetime.TASK, fix.TASK)
    tool_roles = ("eco_sta",)
    hashed_options = ("sdc", "max_paths")

    def sdc(self, engine) -> Path | None:
        if self.options.get("sdc"):
            return engine.project.root / str(self.options["sdc"])
        if self.org_sdc(engine).is_file():
            return self.org_sdc(engine)
        tcl_sdc = engine.project.sdc_dir / "sdc.tcl"
        return tcl_sdc if tcl_sdc.is_file() else None

    def inputs(self, engine) -> list[Path]:
        sdc = self.sdc(engine)
        return [self.post_netlist(engine), self.artifact(engine, EQ2_JSON), *([sdc] if sdc else [])]

    def outputs(self, engine) -> list[Path]:
        rep = self.reports_dir(engine)
        return [f for f in (self.artifact(engine, STA_JSON), rep / "sta.md", *(rep / n for n in REPORTS)) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return self.outputs(engine)

    def missing_input(self, engine) -> str | None:
        if (self.read(engine, EQ2_JSON, {}) or {}).get("status") != "equivalent":
            return "EQ(2) has to pass first (step eco_eq2)"
        return None

    async def run(self, ctx: StepContext) -> None:
        sta = await primetime.run(self, ctx)
        if sta is not None:  # (setup violated)
            await fix.run(self, ctx, sta)
