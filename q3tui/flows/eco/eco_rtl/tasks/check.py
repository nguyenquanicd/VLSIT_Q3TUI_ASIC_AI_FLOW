"""Task `check` of eco_rtl: RTL(F) parsed (pyslang: only the errors the ORG RTL has not) and `eco/rtl.diff` written against the ORG RTL;
the result recorded in `schemas/eco_rtl.json` (the checked netlist edits of the plan go on to eco_patch)."""
from __future__ import annotations

import difflib
from collections import Counter
from pathlib import Path

from q3tui.flows.eco.eco_rtl.tasks.plan import PLAN_JSON
from q3tui.flows.eco.lib.base import RTL_JSON
from q3tui.flows.eco.lib.models import RtlUpdate
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("check", "RTL(F) parsed; eco/rtl.diff against the ORG RTL in ref/")


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


def run(step, ctx: StepContext, out: RtlUpdate, *, key: dict, mapping: dict, update: bool, change: str, owner: list[str], planned: dict,
        asks: dict) -> None:
    """`eco/rtl.diff` and `schemas/eco_rtl.json` (the pending plan is then done: the next request is planned again)."""
    engine, project = ctx.engine, ctx.project
    pairs = [(project.root / o, project.root / f) for f, o in mapping.items()]
    diff = unified_diff(project, pairs)
    old = step.rtl_diff(engine).read_text(errors="replace") if update and step.rtl_diff(engine).is_file() else None
    if old is not None and old == diff:
        # (the same RTL(F): the patch, Post NETLIST and EQ(2) would not run again, the fix loop would stall on the old result)
        step.task(ctx, "check", "the same RTL(F) as before", "failed")
        raise StepFailed(f"the revised RTL(F) is the same as before ({out.summary[:200]}): fix the RTL by hand or give eco_rtl another hint")
    step.rtl_diff(engine).write_text(diff)
    if not diff:
        step.task(ctx, "check", "RTL(F) is the ORG RTL", "failed")
        raise StepFailed(f"RTL(F) is the ORG RTL: no change made for the requirement ({out.summary[:300]})")
    step.write(engine, RTL_JSON, {"key": key, "map": mapping, "summary": out.summary, "changes": [c.model_dump() for c in out.changes],
                                  "concerns": out.concerns, "diff_lines": diff.count("\n"), "change": change,
                                  "by": "rtl flow" if owner else "eco_rtl",
                                  "netlist_edits": [] if planned.get("edit_problems") else list(planned.get("netlist_edits") or []),
                                  "planned_cells": planned.get("new_cells"),
                                  "concern_asks": {**asks, **step.ask_concerns(ctx, {"key": key, "diff": diff}, out.concerns, "RTL(F)")}})
    step.artifact(engine, PLAN_JSON).unlink(missing_ok=True)  # (done: the next request is planned again)
    step.task(ctx, "check", f"parses; {project.rel(step.rtl_diff(engine))}: {diff.count(chr(10))} lines")
    ctx.emit("log", message=f"RTL(F): {out.summary[:200]} ({len(out.changes)} file(s), see {project.rel(step.rtl_diff(engine))})")
