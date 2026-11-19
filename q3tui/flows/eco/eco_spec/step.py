"""ECO step `eco_spec` (project mode): the project's spec updated to the requirement, the smallest change (the ORG spec is in
`ref/<name>/spec/`). Its tasks (`tasks/`, a prompt beside a task's code: `<task>.md`):

- request: the requirement (and the change requests: your review, a Sanity `spec` decision during the ECO) as one change request;
- hand-off: when the spec flow wrote `spec/spec.md`, the request goes to the spec flow's `spec` step and the spec flow runs (spec → parse →
  config: it patches only the sections the request affects; its gate and questions are its own: when it stops there, this step fails until
  you finished there and run eco again — the request is not sent twice);
- edit: a spec that is your own (not the spec flow's): an LLM stage edits the spec documents in place (only spec/, never the intent);
- diff: `eco/spec.diff` against the ORG spec.

The gate is your review. A change request updates the current spec; a changed requirement starts again from the ORG spec. External mode
(RTL from outside the project): nothing to update, the step is skipped."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_spec.tasks import diff, edit, hand_off, request
from q3tui.flows.eco.lib.base import EQ1_JSON, INPUTS_JSON, SPEC_JSON, EcoStep
from q3tui.pipeline.base import StepContext


class Step(EcoStep):
    name = "eco_spec"
    title = "Spec update for the ECO"
    deps = ("eco_eq1",)
    tasks = (request.TASK, hand_off.TASK, edit.TASK, diff.TASK)

    def ref_docs(self, engine) -> list[Path]:
        """The ORG spec documents (ref/<name>/spec/, as the project's spec_documents())."""
        ref = self.ref_dir(engine)
        if self.mode(engine) != "project" or not ref:
            return []
        return [ref / "spec" / d.name for d in engine.project.spec_documents() if (ref / "spec" / d.name).is_file()]

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
        r = request.run(self, ctx)
        if r is None:
            return
        if self.owner_made(ctx.engine, "spec") and ctx.project.spec_dir / "spec.md" in r.docs:
            out = await hand_off.run(self, ctx, r)
            self.task(ctx, "edit", "not needed: the spec flow made the change", "skipped")
        else:
            self.task(ctx, "hand-off", "the spec is your own (the spec flow did not write spec/spec.md): edited here", "skipped")
            out = await edit.run(self, ctx, r)
        diff.run(self, ctx, r, out)
