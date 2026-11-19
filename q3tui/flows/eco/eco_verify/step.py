"""ECO step `eco_verify` (project mode): Verification (the dv flow) and Sanity again on the ECO'd design, before the netlist ECO. You are asked
whether to run them (the `verify` option answers for you; auto-answer takes yes). Yes: the dv flow, then the Sanity flow (analysis, then the
review's hand-off) run within this step; both must pass before `eco_patch`. Their RTL / spec fixes come back to this flow (`eco_rtl` /
`eco_spec`, the smallest change, judged first: lib/ref.py `eco_owner`), never to the rtl flow's generator: this step hands back, the fix loop
updates RTL(F) and runs this step again (bounded by `max_rounds`). A request `eco_rtl` judged not the ECO's to fix ends here, for you to look at.
External mode (a fire-fighting ECO) and "no": skipped. Its tasks (`tasks/`): ask, dv, sanity."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_verify.tasks import ask, dv, sanity
from q3tui.flows.eco.lib.base import RTL_JSON, SPEC_JSON, VERIFY_JSON, EcoStep
from q3tui.pipeline.base import StepContext


class Step(EcoStep):
    name = "eco_verify"
    title = "Verification + Sanity on the ECO'd design"
    deps = ("eco_rtl",)
    tasks = (ask.TASK, dv.TASK, sanity.TASK)
    hashed_options = ("verify",)

    def inputs(self, engine) -> list[Path]:
        files = [self.artifact(engine, RTL_JSON), self.artifact(engine, SPEC_JSON), *self.rtl_f_files(engine), self._q_paths(engine)[1]]
        return [f for f in files if f.is_file()]

    def outputs(self, engine) -> list[Path]:
        return [f for f in (self.artifact(engine, VERIFY_JSON),) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *self._q_paths(engine)]

    def missing_input(self, engine) -> str | None:
        if not self.artifact(engine, RTL_JSON).is_file():
            return "RTL(F) is needed first (step eco_rtl)"
        return None

    async def run(self, ctx: StepContext) -> None:
        if not ask.run(self, ctx):
            return
        yes = self.auto_answer(ctx.engine) or ctx.engine.unattended_run()
        results: dict[str, dict] = {}
        failed = None
        for flow in ("dv", "sanity"):
            ok, note = await (self._dv(ctx, yes) if flow == "dv" else self._sanity(ctx, yes))
            results[flow] = {"passed": ok, "note": note}
            self.task(ctx, flow, note, "done" if ok else "failed")
            ctx.emit("log" if ok else "warning", message=f"ECO verify: {flow} {'passed' if ok else 'did not pass'} — {note}")
            if not ok:
                failed = flow
                break
        sanity.settle(self, ctx, results, failed)

    # (the dv / Sanity runs as methods: tests stand in for them on the class)
    async def _dv(self, ctx: StepContext, yes: bool) -> tuple[bool, str]:
        return await dv.run(self, ctx, yes)

    async def _sanity(self, ctx: StepContext, yes: bool) -> tuple[bool, str]:
        return await sanity.run(self, ctx, yes)
