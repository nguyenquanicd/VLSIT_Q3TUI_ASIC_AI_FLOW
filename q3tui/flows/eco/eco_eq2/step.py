"""ECO step `eco_eq2`: EQ(2), the Post NETLIST against RTL(F) (Formality). Not equivalent: an LLM reads the report with the RTL change and the
patch (`eco/reports/eq2.md`: causes, who owns the fix, the recommended fix) and you are asked how to fix it: the recommended fix, the other step,
your own words (to the step the analysis names; `patch:` / `rtl:` first to choose), or stop. Your answer goes to that step once; the fix loop
then runs it and EQ(2) again. Under auto-answer (pipeline.auto_answer, gate mode auto_answer, --yes) the recommended fix is sent without asking.
Its tasks (one folder each): formality, advise, route."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_eq2.advise import task as advise
from q3tui.flows.eco.eco_eq2.formality import task as formality
from q3tui.flows.eco.eco_eq2.route import task as route_task
from q3tui.flows.eco.eco_eq2.route.task import own_words, route  # noqa: F401 (tests import them from here)
from q3tui.flows.eco.lib.base import APPLY_JSON, EQ2_JSON, EcoStep
from q3tui.pipeline.base import StepContext


class Step(EcoStep):
    name = "eco_eq2"
    title = "EQ(2): RTL(F) vs Post NETLIST"
    deps = ("eco_apply",)
    tasks = (formality.TASK, advise.TASK, route_task.TASK)
    tool_roles = ("asic_lec",)
    hashed_options = ("message_filter", "extra_tcl")

    def inputs(self, engine) -> list[Path]:
        return [self.rtl_f_filelist(engine), *self.rtl_f_files(engine), self.post_netlist(engine), self._q_paths(engine)[1]]

    def outputs(self, engine) -> list[Path]:
        return [f for f in (self.artifact(engine, EQ2_JSON), self.reports_dir(engine) / "eq2.md") if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *self._q_paths(engine)]

    def missing_input(self, engine) -> str | None:
        if not self.post_netlist(engine).is_file() or (self.read(engine, APPLY_JSON, {}) or {}).get("status") != "pass":
            return "the Post NETLIST is needed first (step eco_apply)"
        return None

    async def run(self, ctx: StepContext) -> None:
        prev = self.read(ctx.engine, EQ2_JSON, {}) or {}
        if route_task.send_answers(self, ctx, prev):  # (your answer to a failed EQ(2): sent to its step once)
            return
        result = await formality.run(self, ctx, dict(prev.get("asks") or {}))
        if result is None:  # (equivalent)
            return
        route_task.run(self, ctx, result, await advise.run(self, ctx, result, prev), prev)
