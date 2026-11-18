"""ECO step `eco_spec` (project mode): the project's spec documents updated to the requirement, the smallest change, in place (`spec/*.md`; the
ORG spec is in `ref/<name>/spec/`). An LLM stage edits them (it may write only in spec/, never the intent); code writes `eco/spec.diff` against
the ORG spec. The gate is your review. A change request (your review, a Sanity `spec` decision during the ECO) edits the current spec; a
changed requirement starts again from the ORG spec. External mode (RTL from outside the project): nothing to update, the step is skipped.
The spec flow's own steps (parse, config) take the updated spec when the dv flow runs again (eco_verify)."""
from __future__ import annotations

import difflib
import shutil
from pathlib import Path

from q3tui.core.project import sha256_file
from q3tui.flows import skill_sections
from q3tui.flows.eco.lib.base import EQ1_JSON, INPUTS_JSON, SPEC_JSON, EcoStep
from q3tui.flows.eco.lib.models import RtlUpdate
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext, StepFailed

SYSTEM = skill_sections(Path(__file__).parent / "md" / "skill.md")


class Step(EcoStep):
    name = "eco_spec"
    title = "Spec update for the ECO"
    deps = ("eco_eq1",)

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
        engine, project = ctx.engine, ctx.project
        if self.mode(engine) != "project":
            self.write(engine, SPEC_JSON, {"status": "skipped", "why": "external RTL (a fire-fighting ECO): the spec is not this project's"})
            ctx.emit("log", message="spec update: skipped (external RTL)")
            return
        req = self.requirement(engine)
        refs = self.ref_docs(engine)
        if not refs:
            raise StepFailed(f"no ORG spec document in {project.rel(self.ref_dir(engine) / 'spec')} (the project's spec/*.md, intent excluded)")
        docs = [project.spec_dir / r.name for r in refs]
        key = {"requirement": sha256_file(req), "org": {project.rel(r): sha256_file(r) for r in refs}}
        prev = self.read(engine, SPEC_JSON, {}) or {}
        feedback = list(ctx.feedback)
        update = bool(feedback) and not ctx.regenerate and prev.get("key") == key
        if not update:  # (from the ORG spec again)
            changed = [d for d, r in zip(docs, refs) if not d.is_file() or d.read_bytes() != r.read_bytes()]
            if changed:
                project.backup(changed)
            for d, r in zip(docs, refs):
                if d in changed:
                    shutil.copyfile(r, d)
        task = [f"## The requirement ({project.rel(req)})", req.read_text(errors="replace"), "",
                "## The spec documents: edit them in place (the ORG spec is kept in " + project.rel(refs[0].parent) + ")",
                *[f"- {project.rel(d)}" for d in docs]]
        if update:
            task += ["", "## Change requests on the updated spec", *[f"- {x}" for x in feedback],
                     f"(The changes made so far against the ORG spec: {project.rel(self.spec_diff(engine))}.)"]
        stage = Stage(name="eco_spec", system_prompt=SYSTEM["SPEC"], prompt="\n".join(task), cwd=project.root,
                      builtin_tools=["Read", "Grep", "Glob", "Edit"], output_model=RtlUpdate, write_dirs=[project.spec_dir],
                      deny_dirs=[project.build_dir, project.src_dir, self.eco_dir(engine) / "netlist", self.eco_dir(engine) / "patch",
                                 self.org_dir(engine)])
        intent = project.spec_dir / "intent.md"
        before = intent.read_bytes() if intent.is_file() else None
        out: RtlUpdate = (await ctx.llm(stage)).output
        if intent.is_file() and before is not None and intent.read_bytes() != before:
            intent.write_bytes(before)  # (the intent is yours: the ECO updates the spec documents only)
            ctx.emit("warning", message="spec update: spec/intent.md was edited — put back as it was")
        diff = "".join(x for d, r in zip(docs, refs) for x in difflib.unified_diff(
            r.read_text(errors="replace").splitlines(keepends=True), d.read_text(errors="replace").splitlines(keepends=True),
            fromfile=f"a/{project.rel(r)}", tofile=f"b/{project.rel(d)}"))
        self.spec_diff(engine).parent.mkdir(parents=True, exist_ok=True)
        self.spec_diff(engine).write_text(diff)
        self.write(engine, SPEC_JSON, {"status": "updated" if diff else "unchanged", "key": key, "summary": out.summary,
                                       "changes": [c.model_dump() for c in out.changes], "concerns": out.concerns,
                                       "diff_lines": diff.count("\n")})
        ctx.emit("log", message=f"spec update: {out.summary[:200]} ({diff.count(chr(10))} diff lines, see {project.rel(self.spec_diff(engine))})")
        for c in out.concerns:
            ctx.emit("warning", message=f"spec update: {c}")
