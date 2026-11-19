"""Task `check_requirement` of eco_rtl: the requirement and the ORG RTL against the last run (`key`): a changed one starts again from a fresh
copy of the ORG RTL, the same one with change requests (your review, EQ(2), dv / Sanity) updates the current RTL(F)."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from q3tui.core.project import sha256_file
from q3tui.flows.eco.eco_rtl.concerns import task as concerns
from q3tui.flows.eco.lib.base import RTL_JSON
from q3tui.pipeline.base import StepContext

TASK = ("check_requirement", "the requirement and the ORG RTL against the last run: start again from a fresh copy of the ORG RTL, or update "
                             "RTL(F) on the change requests")
PLAN_JSON = "eco_rtl_plan.json"  # schemas/: the plan of the pending change, the request it answers, the decision


@dataclass
class Rtl:
    """What the run works on: the requirement, the key, the last record, the change requests, update or fresh, and the RTL(F) files
    ({file: its ORG file})."""
    req: Path
    key: dict
    prev: dict
    asks: dict = field(default_factory=dict)
    feedback: list[str] = field(default_factory=list)
    update: bool = False
    mapping: dict = field(default_factory=dict)


def copy_names(files: list[Path]) -> dict[Path, str]:
    """The name of each ORG file in eco/rtl/: its own, or `<parent>__<name>` when two files share a name."""
    seen: dict[str, int] = {}
    for f in files:
        seen[f.name] = seen.get(f.name, 0) + 1
    return {f: (f.name if seen[f.name] == 1 else f"{f.parent.name}__{f.name}") for f in files}


def fresh_copy(step, engine) -> dict[str, str]:
    """eco/rtl/ = the ORG RTL again, with a filelist of the copies (the ORG include dirs and defines kept). {copy: ORG file}.
    Project mode: the project's RTL files are the ORG ones again (from ref/; the filelist is the project's own). {RTL file: ref copy}."""
    from q3tui.hdl.filelist import parse_filelist
    project = engine.project
    if step.mode(engine) == "project":
        ref = step.ref_dir(engine)
        mapping = {}
        for org in step.org_rtl_files(engine):
            dst = project.root / org.relative_to(ref)
            if not dst.is_file() or dst.read_bytes() != org.read_bytes():
                project.backup([dst])
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(org, dst)
            mapping[project.rel(dst)] = project.rel(org)
        return mapping
    fl = parse_filelist(step.org_filelist(engine), project.root)
    d = step.rtl_f_dir(engine)
    if d.is_dir():
        project.backup([p for p in d.rglob("*") if p.is_file()])
        shutil.rmtree(d)
    d.mkdir(parents=True)
    names = copy_names(fl.files)
    mapping = {}
    for org, name in names.items():
        shutil.copyfile(org, d / name)
        mapping[project.rel(d / name)] = project.rel(org)
    lines = [f"+incdir+{x}" for x in fl.incdirs] + [f"+define+{k}" + (f"={v}" if v is not None else "") for k, v in fl.defines.items()]
    lines += list(mapping)
    step.rtl_f_filelist(engine).write_text("\n".join(lines) + "\n")
    return mapping


def run(step, ctx: StepContext) -> Rtl | None:
    """The run's Rtl (a fresh copy made when it starts again); None when this run only took your answers to the concerns."""
    engine, project = ctx.engine, ctx.project
    req = step.requirement(engine)
    key = {"requirement": sha256_file(req), "org": {project.rel(f): sha256_file(f) for f in step.org_rtl_files(engine)}}
    r = Rtl(req, key, step.read(engine, RTL_JSON, {}) or {})
    answers = concerns.answers(step, ctx, r, step.read(engine, PLAN_JSON, {}) or {})
    if answers is None:
        step.task(ctx, "check_requirement", "the same requirement: this run takes your answers to the concerns")
        return None
    r.asks, r.feedback = answers
    r.update = bool(r.feedback) and not ctx.regenerate and r.prev.get("key") == key and step.rtl_f_filelist(engine).is_file()
    # (a fresh copy before the plan: the plan reads the copies in eco/rtl/, the ORG RTL may be outside the project)
    r.mapping = r.prev.get("map") if r.update else fresh_copy(step, engine)
    step.task(ctx, "check_requirement", f"update: {len(r.feedback)} change request(s) on the current RTL(F)" if r.update
              else f"from the ORG RTL ({len(r.mapping)} file(s) as in the ORG)")
    return r
