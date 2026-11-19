"""Task `diff` of eco_spec: `eco/spec.diff` against the ORG spec in `ref/<name>/spec/`, and `schemas/eco_spec.json` (the change, its concerns
asked as questions)."""
from __future__ import annotations

import difflib

from q3tui.flows.eco.eco_spec.tasks.request import Request
from q3tui.flows.eco.lib.base import SPEC_JSON
from q3tui.flows.eco.lib.models import RtlUpdate
from q3tui.pipeline.base import StepContext

TASK = ("diff", "eco/spec.diff against the ORG spec in ref/")


def run(step, ctx: StepContext, r: Request, out: RtlUpdate) -> None:
    engine, project = ctx.engine, ctx.project
    diff = "".join(x for d, ref in zip(r.docs, r.refs) for x in difflib.unified_diff(
        ref.read_text(errors="replace").splitlines(keepends=True), d.read_text(errors="replace").splitlines(keepends=True),
        fromfile=f"a/{project.rel(ref)}", tofile=f"b/{project.rel(d)}"))
    step.spec_diff(engine).parent.mkdir(parents=True, exist_ok=True)
    step.spec_diff(engine).write_text(diff)
    step.write(engine, SPEC_JSON, {"status": "updated" if diff else "unchanged", "key": r.key, "summary": out.summary,
                                   "changes": [c.model_dump() for c in out.changes], "concerns": out.concerns,
                                   "diff_lines": diff.count("\n"),
                                   "concern_asks": {**r.asks, **step.ask_concerns(ctx, {"key": r.key, "diff": diff}, out.concerns, "spec update")}})
    step.task(ctx, "diff", f"{project.rel(step.spec_diff(engine))}: {diff.count(chr(10))} lines" if diff else "the spec is the ORG spec",
              "done" if diff else "skipped")
    ctx.emit("log", message=f"spec update: {out.summary[:200]} ({diff.count(chr(10))} diff lines, see {project.rel(step.spec_diff(engine))})")
