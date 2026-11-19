"""Task `check` of eco_rtl: RTL(F) parses (pyslang; an error the ORG RTL has too is not the change's) and `eco/rtl.diff` is written against
the ORG RTL; an RTL(F) the same as before a change request, or the same as the ORG RTL, fails the step."""
from __future__ import annotations

import difflib
from pathlib import Path

from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("check", "RTL(F) parses, and eco/rtl.diff against the ORG RTL (no change, or the same as before a request: the step fails)")


def unified_diff(project, pairs: list[tuple[Path, Path]]) -> str:
    out = []
    for org, new in pairs:
        a = org.read_text(errors="replace").splitlines(keepends=True) if org.is_file() else []
        b = new.read_text(errors="replace").splitlines(keepends=True) if new.is_file() else []
        out += difflib.unified_diff(a, b, fromfile=f"a/{project.rel(org)}", tofile=f"b/{project.rel(new)}")
    return "".join(out)


def parse_errors(step, engine) -> list[str]:
    """The parse errors RTL(F) has and the ORG RTL has not (an error of the ORG RTL — e.g. `unknown module` of a hard macro that has
    only a .db — is not the change's: it was synthesized that way)."""
    from collections import Counter
    from q3tui.hdl.filelist import parse_filelist
    from q3tui.hdl.parse import parse_design
    root, top = engine.project.root, step.top(engine)

    def errors(filelist: Path) -> list:
        return parse_design(parse_filelist(filelist, root), top).errors

    def key(d) -> tuple[str, str]:  # (the file's name and the message: lines move in an edited file, copies may be renamed)
        return (Path(getattr(d, "file", None) or "").name, d.message)

    new = errors(step.rtl_f_filelist(engine))
    known = Counter(key(d) for d in errors(step.org_filelist(engine))) if new else Counter()
    out = []
    for d in new:
        if known[key(d)] > 0:
            known[key(d)] -= 1
            continue
        out.append(f"{d.file}:{d.line}: {d.message}" if getattr(d, "file", None) else d.message)
    return out


def run(step, ctx: StepContext, r, summary: str) -> str:
    """eco/rtl.diff written; the diff."""
    engine, project = ctx.engine, ctx.project
    pairs = [(project.root / o, project.root / f) for f, o in r.mapping.items()]
    diff = unified_diff(project, pairs)
    old = step.rtl_diff(engine).read_text(errors="replace") if r.update and step.rtl_diff(engine).is_file() else None
    if old is not None and old == diff:
        # (the same RTL(F): the patch, ECO NETLIST and EQ(2) would not run again, the fix loop would stall on the old result)
        step.task(ctx, "check", "the revised RTL(F) is the same as before", "failed")
        raise StepFailed(f"the revised RTL(F) is the same as before ({summary[:200]}): fix eco/rtl/ by hand or give eco_rtl another hint")
    step.rtl_diff(engine).write_text(diff)
    if not diff:
        step.task(ctx, "check", "RTL(F) is the ORG RTL: no change made", "failed")
        raise StepFailed(f"RTL(F) is the ORG RTL: no change made for the requirement ({summary[:300]})")
    step.task(ctx, "check", f"parses; {project.rel(step.rtl_diff(engine))}: {diff.count(chr(10))} lines")
    return diff
