"""ECO step `eco_spec` (project mode): the project's spec documents updated to the requirement, the smallest change, in place (`spec/*.md`; the
ORG spec is in `ref/<name>/spec/`). An LLM stage edits them (it may write only in spec/, never the intent); code writes `eco/spec.diff` against
the ORG spec. The gate is your review. A change request (your review, a Sanity `spec` decision during the ECO) edits the current spec; a
changed requirement starts again from the ORG spec. External mode (RTL from outside the project): nothing to update, the step is skipped.
The spec flow's own steps (parse, config) take the updated spec when the dv flow runs again (eco_verify). Its tasks (one folder each):
check_requirement, edit, concerns, diff."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_spec.check_requirement import task as check_requirement
from q3tui.flows.eco.eco_spec.concerns import task as concerns
from q3tui.flows.eco.eco_spec.diff import task as diff_task
from q3tui.flows.eco.eco_spec.edit import task as edit
from q3tui.flows.eco.lib.base import EQ1_JSON, INPUTS_JSON, SPEC_JSON, EcoStep
from q3tui.pipeline.base import StepContext


class Step(EcoStep):
    name = "eco_spec"
    title = "Spec update for the ECO"
    deps = ("eco_eq1",)
    tasks = (check_requirement.TASK, edit.TASK, concerns.TASK, diff_task.TASK)

    def ref_docs(self, engine) -> list[Path]:
        """The ORG spec documents (ref/<name>/spec/, as the project's spec_documents())."""
        return check_requirement.ref_docs(self, engine)

    def inputs(self, engine) -> list[Path]:
        req = self.requirement(engine)
        return [self.artifact(engine, INPUTS_JSON), *([req] if req and req.is_file() else []), *self.ref_docs(engine), self._q_paths(engine)[1]]

    def outputs(self, engine) -> list[Path]:
        docs = engine.project.spec_documents() if self.mode(engine) == "project" else []
        return [f for f in (self.artifact(engine, SPEC_JSON), self.spec_diff(engine), *docs) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        # (the spec documents are the project's: a reset restores them from ref/ on the next run, it never deletes them)
        return [f for f in (self.artifact(engine, SPEC_JSON), self.spec_diff(engine), *self._q_paths(engine)) if f.is_file()]

    def missing_input(self, engine) -> str | None:
        miss = self.need_inputs(engine)
        if miss:
            return miss
        if (self.read(engine, EQ1_JSON, {}) or {}).get("status") not in ("equivalent", "skipped"):
            return "EQ(1) has to pass (or be skipped) first (step eco_eq1)"
        return None

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        if self.mode(engine) != "project":
            self.write(engine, SPEC_JSON, {"status": "skipped", "why": "external RTL (a fire-fighting ECO): the spec is not this project's"})
            self.task(ctx, "check_requirement", "skipped: external RTL (a fire-fighting ECO), no spec to update", "skipped")
            ctx.emit("log", message="spec update: skipped (external RTL)")
            return
        s = check_requirement.run(self, ctx)
        if s is None:
            return  # (a run for your answers to the concerns)
        out = await edit.run(self, ctx, s)
        diff = diff_task.run(self, ctx, s)
        asks = concerns.ask(self, ctx, s, diff, out.concerns)
        self.write(engine, SPEC_JSON, {"status": "updated" if diff else "unchanged", "key": s.key, "summary": out.summary,
                                       "changes": [c.model_dump() for c in out.changes], "concerns": out.concerns,
                                       "diff_lines": diff.count("\n"), "concern_asks": asks})
        ctx.emit("log", message=f"spec update: {out.summary[:200]} ({diff.count(chr(10))} diff lines, see {project.rel(self.spec_diff(engine))})")
