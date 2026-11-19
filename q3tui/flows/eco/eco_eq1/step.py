"""ECO step `eco_eq1`: EQ(1), the ORG netlist against the ORG RTL (Formality). The asic flow's `asic_lec` is this same check: when it passed on
the same netlist and RTL, you choose between its result and a new run; without it you choose whether to run EQ(1) at all (skipped: said in the
result, the flow goes on). Not equivalent stops the flow with the causes and what to do (`eco/reports/eq1.md`).
Its tasks (one folder each): decide, formality, advise."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_eq1.advise import task as advise
from q3tui.flows.eco.eco_eq1.decide import task as decide
from q3tui.flows.eco.eco_eq1.decide.task import lec_reuse  # noqa: F401  (tests import it from here)
from q3tui.flows.eco.eco_eq1.formality import task as formality
from q3tui.flows.eco.lib.base import EQ1_JSON, INPUTS_JSON, EcoStep
from q3tui.pipeline.base import StepContext, StepFailed


class Step(EcoStep):
    name = "eco_eq1"
    title = "EQ(1): ORG RTL vs ORG netlist"
    deps = ("eco_inputs",)
    tasks = (decide.TASK, formality.TASK, advise.TASK)
    tool_roles = ("asic_lec",)
    hashed_options = ("message_filter", "extra_tcl")

    def inputs(self, engine) -> list[Path]:
        lec = engine.project.schemas_dir / "asic_lec.json"
        return [self.artifact(engine, INPUTS_JSON), self.org_netlist(engine), *self.org_rtl_files(engine), self._q_paths(engine)[1],
                *([lec] if lec.is_file() else [])]

    def outputs(self, engine) -> list[Path]:
        return [x for x in (self.artifact(engine, EQ1_JSON), self.reports_dir(engine) / "eq1.md") if x.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *self._q_paths(engine)]

    def missing_input(self, engine) -> str | None:
        return self.need_inputs(engine)

    async def run(self, ctx: StepContext) -> None:
        engine = ctx.engine
        inputs = self.inputs_data(engine)
        rtl = self.org_rtl_files(engine)
        if not rtl:
            raise StepFailed(f"no RTL file in {inputs.get('rtl')}")
        self.artifact(engine, EQ1_JSON).unlink(missing_ok=True)
        got = decide.run(self, ctx, inputs, rtl)
        if got is None:
            return
        qid, answer, reuse = got
        result = await formality.run(self, ctx, rtl, qid, answer, reuse)
        if result is not None:
            await advise.run(self, ctx, inputs, result, qid)
