"""Task `request` of eco_spec: the requirement (and the change requests: your review, a Sanity `spec` decision during the ECO) as one change
request. A changed requirement starts again from the ORG spec (`ref/<name>/spec/`); a change request updates the current spec. External mode
(RTL from outside the project): nothing to update, the step is skipped. Its prompt (`request.md`) is the text the spec flow gets."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from q3tui.core.project import sha256_file, sha256_json
from q3tui.flows.eco.lib.base import SPEC_JSON, task_prompt
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("request", "the requirement and the change requests, as one change request")
PROMPT = task_prompt(__file__)


@dataclass
class Request:
    req: Path  # the requirement
    docs: list[Path]  # the spec documents (spec/)
    refs: list[Path]  # the ORG ones (ref/<name>/spec/)
    key: dict
    asks: dict  # the concern questions asked before
    feedback: list[str]  # the change requests
    update: bool  # a change request on the current spec (not from the ORG spec again)
    qkey: str  # this request (handed off once)


def text(project, req: Path) -> str:
    """The requirement as the change request the spec flow's `spec` step gets."""
    return PROMPT.replace("{path}", project.rel(req)).replace("{requirement}", req.read_text(errors="replace").strip())


def run(step, ctx: StepContext) -> Request | None:
    """The request, the spec documents set back to the ORG spec unless it updates them; None when there is nothing to do (external mode, or a
    run for your answers to the concerns)."""
    engine, project = ctx.engine, ctx.project
    if step.mode(engine) != "project":
        step.write(engine, SPEC_JSON, {"status": "skipped", "why": "external RTL (a fire-fighting ECO): the spec is not this project's"})
        step.task(ctx, "request", "external RTL (a fire-fighting ECO): no spec to update", "skipped")
        ctx.emit("log", message="spec update: skipped (external RTL)")
        return None
    req = step.requirement(engine)
    refs = step.ref_docs(engine)
    if not refs:
        raise StepFailed(f"no ORG spec document in {project.rel(step.ref_dir(engine) / 'spec')} (the project's spec/*.md, intent excluded)")
    docs = [project.spec_dir / r.name for r in refs]
    key = {"requirement": sha256_file(req), "org": {project.rel(r): sha256_file(r) for r in refs}}
    prev = step.read(engine, SPEC_JSON, {}) or {}
    asks, answered, open_ = step.concern_answers(ctx, prev, key)
    feedback = [*ctx.feedback, *answered]
    if asks and not feedback and not ctx.regenerate:  # (a run for your answers to the concerns: each one kept, or still open)
        step.write(engine, SPEC_JSON, {**prev, "concern_asks": asks})
        ctx.emit("warning" if open_ else "log", message=f"spec update: answer {', '.join(open_)} (the concerns of the change), then run again"
                 if open_ else "spec update: every concern answered — the change is kept")
        return None
    update = bool(feedback) and not ctx.regenerate and prev.get("key") == key
    qkey = sha256_json({"key": key, "feedback": feedback})[:16]
    # (handed off already — this run comes after you finished in the spec flow: spec/ holds its change, never the ORG spec again)
    handed = engine.state.step_meta.get(step.name, {}).get("handed") == qkey and not ctx.regenerate
    if not update and not handed:  # (from the ORG spec again)
        changed = [d for d, r in zip(docs, refs) if not d.is_file() or d.read_bytes() != r.read_bytes()]
        if changed:
            project.backup(changed)
        for d, r in zip(docs, refs):
            if d in changed:
                shutil.copyfile(r, d)
    step.task(ctx, "request", f"the requirement ({project.rel(req)})" + (f" and {len(feedback)} change request(s)" if feedback else ""))
    return Request(req, docs, refs, key, asks, feedback, update, qkey)
