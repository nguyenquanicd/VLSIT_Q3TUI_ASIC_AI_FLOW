"""The review items of an output (spec/flow.md "`outputs[].view`", spec/engine.md "Gates"): a section of a
Markdown file, or a row of a JSON file, when the view has `review: true`."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from q3tui.engine.artifacts import json_path

SECTION_MARK = re.compile(r"^<!--\s*section:\s*([^>]+?)\s*-->\s*$", re.MULTILINE)
HEADING = re.compile(r"^##\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def sections(text: str, by: str = "marker") -> dict[str, str]:
    """The sections of a Markdown file: from `<!-- section: id -->` (marker) or a `## Heading` to the next."""
    pat = SECTION_MARK if by == "marker" else HEADING
    marks = list(pat.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1).strip()] = text[m.end():end].strip()
    return out


def rows(data, view: dict) -> dict[str, object]:
    found = json_path(data, view.get("rows", "$"))
    items = found[0] if len(found) == 1 and isinstance(found[0], (list, dict)) else found
    id_field = view.get("id")
    out: dict[str, object] = {}
    if isinstance(items, dict):
        return {str(k): v for k, v in items.items()}
    for n, row in enumerate(items):
        key = str(row.get(id_field)) if isinstance(row, dict) and id_field and row.get(id_field) is not None else str(n)
        out[key] = row
    return out


def review_items(view: dict | None, files: list[Path]) -> dict[str, str]:
    """item -> the hash of its content, for an output whose view reviews items; {} otherwise."""
    if not view or not view.get("review") or not files:
        return {}
    f = files[0]
    try:
        if view.get("kind") == "sections":
            return {k: _digest(v) for k, v in sections(f.read_text(), view.get("by", "marker")).items()}
        if view.get("kind") == "table":
            return {k: _digest(json.dumps(v, sort_keys=True)) for k, v in rows(json.loads(f.read_text()), view).items()}
    except (OSError, ValueError):
        return {}
    return {}
