"""What the tabs of Main show for each output (spec/flow.md "`outputs[].view`"): its items and their detail.
No Textual here."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from q3tui.engine import Engine
from q3tui.engine.artifacts import is_glob, json_path
from q3tui.engine.views import rows, sections


@dataclass
class Item:
    id: str
    label: str
    state: str = ""  # ok | warn | error | todo, or the review status
    detail: str = ""  # Markdown


@dataclass
class View:
    artifact: str
    kind: str  # document | files | sections | table
    title: str
    review: bool = False
    items: list[Item] = field(default_factory=list)
    text: str = ""  # a document
    missing: bool = False


def _state_of(row, spec: dict | None) -> str:
    if not spec or not isinstance(row, dict):
        return ""
    value = row.get(spec.get("field", "state"))
    return (spec.get("map") or {}).get(value, str(value) if value is not None else "")


def _cell(row, col) -> str:
    name = col if isinstance(col, str) else col.get("field", "")
    v = row.get(name) if isinstance(row, dict) else row
    return "" if v is None else str(v)


def build_views(engine: Engine, sid: str) -> list[View]:
    inst = engine.flow.instances[sid]
    reviews = engine.state.step(sid).reviews
    out: list[View] = []
    for o in inst.outputs:
        files = engine.artifacts.files(o.artifact)
        pattern = engine.artifacts.pattern(o.artifact) or ""
        view = dict(o.view or {})
        kind = view.get("kind") or ("files" if is_glob(pattern) else "document")
        v = View(o.artifact, kind, view.get("title") or o.artifact, bool(view.get("review")))
        status = reviews.get(o.artifact, {})
        if not files:
            v.missing = True
            out.append(v)
            continue
        root = engine.root
        try:
            if kind == "document":
                v.text = files[0].read_text(errors="replace")
            elif kind == "files":
                v.items = [Item(str(f.relative_to(root)), str(f.relative_to(root)),
                                detail=_fenced(f)) for f in files]
            elif kind == "sections":
                for name, body in sections(files[0].read_text(errors="replace"), view.get("by", "marker")).items():
                    v.items.append(Item(name, name, status.get(name, {}).get("status", ""), body))
            elif kind == "table":
                data = json.loads(files[0].read_text())
                cols = view.get("columns") or []
                detail_fields = view.get("detail") or []
                for rid, row in rows(data, view).items():
                    label = "  ".join(_cell(row, c) for c in cols[:3]) or rid
                    detail = "\n\n".join(f"**{d}**: {_cell(row, d)}" for d in detail_fields) or \
                        f"```json\n{json.dumps(row, indent=2)}\n```"
                    state = status.get(rid, {}).get("status", "") if v.review else _state_of(row, view.get("state"))
                    v.items.append(Item(rid, label, state, detail))
        except (OSError, ValueError) as exc:
            v.text = f"Cannot show `{o.artifact}`: {exc}"
            v.kind = "document"
        out.append(v)
    return out


def _fenced(f: Path) -> str:
    try:
        text = f.read_text(errors="replace")
    except OSError as exc:
        return str(exc)
    if f.suffix == ".md":
        return text
    lang = {".sv": "systemverilog", ".v": "verilog", ".py": "python", ".json": "json", ".yaml": "yaml",
            ".tcl": "tcl"}.get(f.suffix, "")
    return f"```{lang}\n{text}\n```"


__all__ = ["Item", "View", "build_views", "json_path"]
