"""Task `check_requirement` of eco_spec: the requirement and the ORG spec against the last run (`key`): a changed one starts again from the
ORG spec (the spec documents restored from ref/), the same one with change requests updates the current spec."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from q3tui.core.project import sha256_file
from q3tui.flows.eco.eco_spec.concerns import task as concerns
from q3tui.flows.eco.lib.base import SPEC_JSON
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("check_requirement", "the requirement and the ORG spec against the last run: start again from the ORG spec, or update the current "
                             "one on the change requests")


@dataclass
class Spec:
    """What the run works on: the requirement, the ORG spec documents and the project's, the key, the last record and the change requests."""
    req: Path
    refs: list[Path]
    docs: list[Path]
    key: dict
    prev: dict
    asks: dict = field(default_factory=dict)
    feedback: list[str] = field(default_factory=list)
    update: bool = False


def ref_docs(step, engine) -> list[Path]:
    """The ORG spec documents (ref/<name>/spec/, as the project's spec_documents())."""
    ref = step.ref_dir(engine)
    if step.mode(engine) != "project" or not ref:
        return []
    return [ref / "spec" / d.name for d in engine.project.spec_documents() if (ref / "spec" / d.name).is_file()]


def run(step, ctx: StepContext) -> Spec | None:
    """The run's Spec, the documents restored when it starts again; None when this run only took your answers to the concerns."""
    engine, project = ctx.engine, ctx.project
    req = step.requirement(engine)
    refs = ref_docs(step, engine)
    if not refs:
        step.task(ctx, "check_requirement", "no ORG spec document", "failed")
        raise StepFailed(f"no ORG spec document in {project.rel(step.ref_dir(engine) / 'spec')} (the project's spec/*.md, intent excluded)")
    docs = [project.spec_dir / r.name for r in refs]
    key = {"requirement": sha256_file(req), "org": {project.rel(r): sha256_file(r) for r in refs}}
    s = Spec(req, refs, docs, key, step.read(engine, SPEC_JSON, {}) or {})
    answers = concerns.answers(step, ctx, s)
    if answers is None:
        step.task(ctx, "check_requirement", "the same requirement: this run takes your answers to the concerns")
        return None
    s.asks, s.feedback = answers
    s.update = bool(s.feedback) and not ctx.regenerate and s.prev.get("key") == key
    if s.update:
        step.task(ctx, "check_requirement", f"update: {len(s.feedback)} change request(s) on the current spec")
        return s
    changed = [d for d, r in zip(docs, refs) if not d.is_file() or d.read_bytes() != r.read_bytes()]
    if changed:
        project.backup(changed)
    for d, r in zip(docs, refs):
        if d in changed:
            shutil.copyfile(r, d)
    step.task(ctx, "check_requirement", f"from the ORG spec ({len(changed)} document(s) restored from {project.rel(refs[0].parent)})")
    return s
