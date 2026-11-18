"""The ORG design of an ECO, kept in `ref/<name>/` (docs/spec/eco-flow.md "ref/"), and the pointer to it, `eco/ref.json`.

Two modes, from where the ORG RTL is:
- `project`: the RTL of this project (`src/rtl`, made by the VLSI flows). The ECO modifies the project in place (spec, RTL); `ref/<name>/` keeps
  the un-ECO'd `spec/`, `src/`, `constraints/`, `schemas/` and the ORG netlist. dv / Sanity may run again on the modified RTL, and their RTL
  fixes come back to `eco_rtl` (the smallest change), not to the rtl flow's generator.
- `external`: a filelist outside the project ("fire-fighting" ECO): the RTL files and the ORG netlist are copied to `ref/<name>/`; no spec
  update, no dv / Sanity.

`eco/ref.json` is written once per ECO and no reset deletes it (a run again never snapshots a project the ECO already changed); `ref/` is never
deleted by the flow. A new ECO: delete `eco/ref.json`."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from q3tui.core.project import read_json, write_json

REF_JSON = "ref.json"  # in eco/
SNAPSHOT = ("spec", "src", "constraints", "schemas")  # (project mode; the folder names come from the project)
RTL_FILELIST = "rtl.f"  # in ref/<name>/: the ORG RTL, project-relative paths of the copies


def pointer_path(project) -> Path:
    return project.root / "eco" / REF_JSON


def pointer(project) -> dict:
    return read_json(pointer_path(project), {}) or {}


def mode_of(project, filelist: Path) -> str:
    """`project` when the ORG filelist is the project's RTL (under src/rtl), else `external`."""
    try:
        filelist.resolve().relative_to(project.rtl_dir.resolve())
        return "project"
    except ValueError:
        return "external"


def unique_dir(project, name: str, now: datetime | None = None) -> Path:
    """`ref/<name>`, or `ref/<name>_DDMMYYYY_HHMMSS` when that one exists already."""
    base = project.root / "ref"
    d = base / name
    if not d.exists():
        return d
    return base / f"{name}_{(now or datetime.now()).strftime('%d%m%Y_%H%M%S')}"


def clean_name(text: str) -> str:
    """A folder name from your answer (`name=<x>`, or the text itself)."""
    import re
    m = re.search(r"name\s*=\s*([^\s=]+)", text) or re.search(r"name\s*:\s*([^\s=]+)\s*$", text)
    raw = m.group(1) if m else text.strip().split()[-1] if text.strip() else ""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw.strip("\"'/")) or "org"


def _copytree(src: Path, dst: Path, skip) -> None:
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if not f.is_file() or skip(rel):
            continue
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dst / rel)  # (copyfile: in a shared project, copying mode / mtime onto another user's file fails)


def snapshot(project, ref: Path, mode: str, filelist: Path, rtl_files: list[Path], netlist: Path, top: str) -> dict:
    """Copy the ORG design to `ref`; returns the pointer record (written by the caller)."""
    ref.mkdir(parents=True, exist_ok=False)
    root = project.root
    if mode == "project":
        for name in SNAPSHOT:
            src = root / name
            if src.is_dir():
                # (the ECO's own results are not the ORG design)
                _copytree(src, ref / name, lambda rel: rel.parts[0].startswith("eco_") or (rel.parts[0] == "questions" and rel.name.startswith("eco_")))
        org = [ref / f.resolve().relative_to(root.resolve()) for f in rtl_files]
    else:
        d = ref / "rtl"
        d.mkdir()
        names: dict[str, int] = {}
        org = []
        for f in rtl_files:
            names[f.name] = names.get(f.name, 0) + 1
            dst = d / (f.name if names[f.name] == 1 else f"{names[f.name]}__{f.name}")
            shutil.copyfile(f, dst)
            org.append(dst)
        # shortcut: the external filelist's +incdir / +define are not kept (a flat copy of its files), add them when a design needs them
    missing = [str(f) for f in org if not f.is_file()]
    if missing:
        raise FileNotFoundError("ORG RTL file(s) not under the project: " + ", ".join(missing[:5]))
    (ref / RTL_FILELIST).write_text("".join(f"{project.rel(f)}\n" for f in org))
    nd = ref / "netlist"
    nd.mkdir()
    for suffix in (".v", ".sdc", ".svf"):
        src = netlist.with_suffix(suffix)
        if src.is_file():
            shutil.copyfile(src, nd / f"{top}{suffix}")
    return {"name": ref.name, "path": project.rel(ref), "mode": mode, "created": datetime.now().isoformat(timespec="seconds"),
            "sources": {"rtl": str(filelist), "netlist": str(netlist)}, "rtl_files": {project.rel(f): project.rel(o) for f, o in zip(rtl_files, org)}
            if mode == "project" else {str(f): project.rel(o) for f, o in zip(rtl_files, org)}}


def save_pointer(project, record: dict) -> None:
    pointer_path(project).parent.mkdir(parents=True, exist_ok=True)
    write_json(pointer_path(project), record)


def eco_owner(project) -> str | None:
    """The flow that owns RTL / spec fixes while a project-mode ECO is on (`eco`), else None (the usual owner)."""
    return "eco" if pointer(project).get("mode") == "project" else None


ECO_STEP = {"rtl": "eco_rtl", "spec": "eco_spec"}  # a fix for the rtl flow's step → the ECO flow's step that makes it the smallest way
