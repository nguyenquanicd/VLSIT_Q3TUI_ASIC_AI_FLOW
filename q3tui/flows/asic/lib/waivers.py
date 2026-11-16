"""Waivers of the ASIC synthesis report (`reviews/asic_synth_waivers.json`: yours, kept on reset; docs/spec/asic-flow.md "Waivers").

What the report has that can be waived (`report_items`, code: the ground truth is the tool's reports):
- a constraint group of report_constraint (`min_delay/hold`, `max_transition`, …): every violation of the group, up to `max_ns` for a
  timing group (waived from the TUI at the group's worst slack: a worse one later is not covered);
- one violation (`<group>:<endpoint>`);
- a warning code of check_design or of the Design Compiler log (`LINT-28`, `VER-318`, …): acknowledged, it no longer asks for a look.
A waived violation does not fail the verdict; every waiver keeps its reason."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

FILE = "asic_synth_waivers.json"
_CODE = re.compile(r"^(?:Warning|Error):.*\(([A-Z]+-\d+)\)\s*$")


def path(project) -> Path:
    return project.reviews_dir / FILE


def load(project) -> list[dict]:
    f = path(project)
    try:
        return list(json.loads(f.read_text())) if f.is_file() else []
    except (OSError, ValueError):
        return []


def save(project, items: list[dict]) -> None:
    f = path(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(items, indent=2) + "\n")


def warning_codes(*texts: str) -> dict[str, dict]:
    """{code: {count, sample}} of the warnings (and errors) with a message code in the given reports / logs."""
    out: dict[str, dict] = {}
    for text in texts:
        for ln in text.splitlines():
            m = _CODE.match(ln.strip())
            if m:
                e = out.setdefault(m.group(1), {"count": 0, "sample": ln.strip()[:200]})
                e["count"] += 1
    return out


def endpoint(item: dict) -> str:
    return item["line"].split()[0] if item["line"].split() else ""


def covers(w: dict, item: dict) -> bool:
    """Whether waiver `w` covers violation `item` ({group, line, slack_ns})."""
    key = w.get("key", "")
    if w.get("what") == "item":
        return key == f"{item['group']}:{endpoint(item)}"
    if w.get("what") != "group" or key != item["group"]:
        return False
    cap = w.get("max_ns")
    return cap is None or item["slack_ns"] is None or -item["slack_ns"] <= float(cap) + 1e-9


def apply(waivers: list[dict], items: list[dict], codes: dict[str, dict]) -> tuple[list[dict], list[dict], dict[str, dict], dict[str, dict]]:
    """(open violations, waived violations, open warning codes, waived warning codes)."""
    waived = [i for i in items if any(covers(w, i) for w in waivers)]
    open_ = [i for i in items if i not in waived]
    wcodes = {w["key"] for w in waivers if w.get("what") == "code"}
    return open_, waived, {c: v for c, v in codes.items() if c not in wcodes}, {c: v for c, v in codes.items() if c in wcodes}


def from_reports(project, data: dict) -> dict:
    """`groups_violated` and `warnings` as the scoring of asic_synth writes them, from the reports themselves — for a JSON of a run before
    waivers existed (the tab lists what can be waived before the next run)."""
    from q3tui.flows.asic.lib import dc

    rep = project.build_dir / "syn" / "asic" / "reports"
    def text(f: Path) -> str:
        return f.read_text(errors="replace") if f.is_file() else ""
    log = project.root / data["log"] if data.get("log") else None
    items = dc.violation_items(text(rep / "constraints.rpt"))
    codes = warning_codes(text(rep / "check_design.rpt"), text(log) if log else "")
    open_, _w, open_codes, waived_codes = apply(load(project), items, codes)
    groups: dict[str, dict] = {}
    for v in items:
        e = groups.setdefault(v["group"], {"count": 0, "open": 0, "worst_ns": None, "sample": v["line"][:160]})
        e["count"] += 1
        e["open"] += v in open_
        if v["slack_ns"] is not None and (e["worst_ns"] is None or v["slack_ns"] < e["worst_ns"]):
            e["worst_ns"] = v["slack_ns"]
    return {**data, "groups_violated": groups, "warnings": {**open_codes, **{c: {**v, "waived": True} for c, v in waived_codes.items()}}}


def report_items(data: dict) -> list[dict]:
    """What the TUI lists: one row per constraint group and per warning code of `asic_synth.json` — {key, what, title, count, worst_ns, waived}."""
    rows = []
    for g, e in sorted((data.get("groups_violated") or {}).items()):
        rows.append({"key": g, "what": "group", "title": f"constraint {g}", "count": e["count"], "worst_ns": e.get("worst_ns"),
                     "open": e.get("open", e["count"]), "sample": e.get("sample", "")})
    for c, e in sorted((data.get("warnings") or {}).items()):
        rows.append({"key": c, "what": "code", "title": f"warning {c}", "count": e["count"], "worst_ns": None,
                     "open": 0 if e.get("waived") else e["count"], "sample": e.get("sample", "")})
    return rows


def add(project, what: str, key: str, reason: str, max_ns: float | None = None) -> str:
    if what not in ("group", "item", "code") or not key.strip():
        raise ValueError("what is group | item | code, and the key names it (min_delay/hold, min_delay/hold:<endpoint>, LINT-28)")
    items = [w for w in load(project) if not (w.get("what") == what and w.get("key") == key)]
    w = {"what": what, "key": key.strip(), "reason": reason.strip() or "waived", "at": datetime.now().isoformat(timespec="seconds")}
    if max_ns is not None:
        w["max_ns"] = round(float(max_ns), 4)
    items.append(w)
    save(project, items)
    return f"waived {what} {key}" + (f" up to {w['max_ns']:g} ns" if "max_ns" in w else "") + f": {w['reason']} (asic_synth scores its reports again on the next run, no synthesis)"


def remove(project, key: str) -> str:
    items = load(project)
    kept = [w for w in items if w.get("key") != key]
    if len(kept) == len(items):
        raise ValueError(f"no waiver for {key}")
    save(project, kept)
    return f"waiver of {key} removed"
