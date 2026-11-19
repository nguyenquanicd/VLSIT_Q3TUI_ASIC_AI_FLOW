"""Task `diff` of eco_spec: `eco/spec.diff`, the updated spec documents against the ORG spec."""
from __future__ import annotations

import difflib

from q3tui.pipeline.base import StepContext

TASK = ("diff", "eco/spec.diff: the updated spec against the ORG spec")


def run(step, ctx: StepContext, s) -> str:
    project = ctx.project
    diff = "".join(x for d, r in zip(s.docs, s.refs) for x in difflib.unified_diff(
        r.read_text(errors="replace").splitlines(keepends=True), d.read_text(errors="replace").splitlines(keepends=True),
        fromfile=f"a/{project.rel(r)}", tofile=f"b/{project.rel(d)}"))
    path = step.spec_diff(ctx.engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(diff)
    step.task(ctx, "diff", f"{project.rel(path)}: {diff.count(chr(10))} lines" if diff else "no change against the ORG spec")
    return diff
