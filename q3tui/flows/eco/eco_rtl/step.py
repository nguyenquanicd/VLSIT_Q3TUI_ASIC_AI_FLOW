"""ECO step `eco_rtl`: RTL(F). Code copies the ORG RTL to `eco/rtl/` (with its filelist); an LLM stage edits that copy to do what the requirement
asks (it may write only there; the netlists, the patch and build/ are denied). Code then writes `eco/rtl.diff` and parses RTL(F) (pyslang): an
error goes back to the LLM once, then fails the step. A change request (your review, EQ(2)) edits the current RTL(F); a changed requirement or
ORG RTL starts again from a fresh copy.

Before any edit a read-only stage plans the smallest change (an ECO changes as little as it can). When the requirement or a change request
prescribes how to make the change and the plan finds a smaller one with the same required function, you are asked (blocking): the smaller
change (recommended; auto-answer takes it), the change as asked, or your own words. The decision is kept with the request it answers.
Its tasks (one folder each): check_requirement, plan, decide, edit, concerns, check."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_rtl.check import task as check
from q3tui.flows.eco.eco_rtl.check_requirement import task as check_requirement
from q3tui.flows.eco.eco_rtl.check_requirement.task import PLAN_JSON
from q3tui.flows.eco.eco_rtl.concerns import task as concerns
from q3tui.flows.eco.eco_rtl.decide import task as decide
from q3tui.flows.eco.eco_rtl.edit import task as edit
from q3tui.flows.eco.eco_rtl.plan import task as plan
from q3tui.flows.eco.lib.base import EQ1_JSON, INPUTS_JSON, RTL_JSON, SPEC_JSON, EcoStep
from q3tui.pipeline.base import StepContext


class Step(EcoStep):
    name = "eco_rtl"
    title = "RTL(F): the RTL updated to the requirement"
    deps = ("eco_spec",)
    tasks = (check_requirement.TASK, plan.TASK, decide.TASK, edit.TASK, concerns.TASK, check.TASK)

    def inputs(self, engine) -> list[Path]:
        req = self.requirement(engine)
        spec = [self.artifact(engine, SPEC_JSON), self.spec_diff(engine)] if self.mode(engine) == "project" else []
        return [self.artifact(engine, INPUTS_JSON), self.artifact(engine, EQ1_JSON), *([req] if req else []), *self.org_rtl_files(engine),
                *[f for f in spec if f.is_file()], self._q_paths(engine)[1]]

    def outputs(self, engine) -> list[Path]:
        files = [self.artifact(engine, RTL_JSON), self.rtl_diff(engine), self.rtl_f_filelist(engine), *self.rtl_f_files(engine)]
        return [f for f in files if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), self.artifact(engine, PLAN_JSON), *self._q_paths(engine)]

    def missing_input(self, engine) -> str | None:
        miss = self.need_inputs(engine)
        if miss:
            return miss
        status = (self.read(engine, EQ1_JSON, {}) or {}).get("status")
        if status not in ("equivalent", "skipped"):
            return "EQ(1) has to pass (or be skipped) first (step eco_eq1)"
        if self.mode(engine) == "project" and not (self.read(engine, SPEC_JSON, {}) or {}).get("status"):
            return "the spec update first (step eco_spec)"
        return None

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        r = check_requirement.run(self, ctx)
        if r is None:
            return  # (a run for your answers to the concerns)
        change = decide.run(self, ctx, r, await plan.run(self, ctx, r))
        if change is None:
            return  # (waiting for your answer)
        if r.update and change.strip().lower().startswith("no rtl change"):
            # (a dv / Sanity request the plan judged not the ECO's to fix: RTL(F) stays; eco_verify reports it instead of looping)
            self.write(engine, RTL_JSON, {**r.prev, "concern_asks": r.asks,
                                          "declined": [*r.prev.get("declined", []), {"requests": r.feedback, "why": change}]})
            self.artifact(engine, PLAN_JSON).unlink(missing_ok=True)
            self.task(ctx, "edit", f"not made: {change}", "skipped")
            ctx.emit("warning", message=f"RTL(F) kept as it is: {change[:300]}")
            return
        out = await edit.run(self, ctx, r, change)
        diff = check.run(self, ctx, r, out.summary)
        self.write(engine, RTL_JSON, {"key": r.key, "map": r.mapping, "summary": out.summary, "changes": [c.model_dump() for c in out.changes],
                                      "concerns": out.concerns, "diff_lines": diff.count("\n"), "change": change,
                                      "concern_asks": concerns.ask(self, ctx, r, diff, out.concerns)})
        self.artifact(engine, PLAN_JSON).unlink(missing_ok=True)  # (done: the next request is planned again)
        ctx.emit("log", message=f"RTL(F): {out.summary[:200]} ({len(out.changes)} file(s), see {project.rel(self.rtl_diff(engine))})")
