"""The waiver review's data: the decision of each violation, the VC Static waiver commands, the knowledge the review applies, and how a
fix is handed to the flow that owns it.

VC Static numbers its violations per run (`CDC:48` is another violation the next time), so a violation is identified by what it is
(`signature`: the tag and the objects, or the message) and a waiver names it that way."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ACTIONS = ("waive", "fix_rtl", "spec", "sdc", "ask")
OPEN_ASKING = ("sdc", "ask")  # the decisions that wait for you


class Decision(BaseModel):
    id: str = Field(description="The violation id from the report (V1, V2, …)")
    action: Literal["waive", "fix_rtl", "spec", "sdc", "ask"] = Field(
        description="waive: safe, under a knowledge rule whose conditions you verified, or by a design reason with its evidence; "
                    "fix_rtl: change one RTL module; spec: the spec owner has to decide; "
                    "sdc: a constraint is missing or wrong in the SDC (a plain SDC command in sdc_request is added to constraints/sdc/extra.tcl on hand-off; the user decides otherwise); "
                    "ask: you cannot verify a condition and nothing else settles it: ask the user")
    module: str = Field("", description="action fix_rtl: the module (file name without extension); empty otherwise")
    reason: str = Field(description="waive: why it is safe, citing the evidence (file:line, signal) for each condition; "
                                    "fix_rtl / spec / sdc: what is wrong or undecided; ask: what you checked and what is missing")
    change: str = Field("", description="fix_rtl: the structural change, concretely; spec: the question for the spec; empty otherwise")
    rule: str = Field("", description="waive: the knowledge case it relies on (K1, U2, …); empty for a plain design reason")
    sdc_request: str = Field("", description="action sdc: the constraint to add or change, as one Tcl command with the real object names "
                                             "(e.g. set_max_delay 15.0 -from {…} -to {…}), and where; empty otherwise")
    question: str = Field("", description="action ask / sdc: ONE clear question for the user; empty for the others")
    options: list[str] = Field(default_factory=list, description="action ask: two to four suggested answers; empty otherwise")


class Review(BaseModel):
    decisions: list[Decision] = Field(description="One decision for every violation id of the report (a group: one for its id, which applies to "
                                                  "all its members; a member that differs: its own decision too), none missing, none invented")
    summary: str = Field("", description="Two or three sentences: what was waived, what needs RTL, spec, SDC work or the user")


def _glob(name: str) -> str:
    return name.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")  # (waive_cdc patterns are globs: `[7:0]` is not a range)


def signature(v: dict) -> tuple:
    f = v.get("fields") or {}
    return (v["tag"], f.get("SrcObject") or f.get("ConvergencePoint") or v.get("message", ""), f.get("DestObject") or "")


def sig_id(role: str, v: dict) -> str:
    """A stable id of a violation across runs (the `V` numbers are not): the id of its question."""
    return f"{role.upper()}-" + hashlib.sha256("\0".join(signature(v)).encode()).hexdigest()[:6]


def _comment(d: dict) -> str:
    why = " ".join(f"{d.get('rule') or 'design'}: {d.get('reason', '')}".split())[:300]
    return why.replace("{", "(").replace("}", ")").replace("\\", "/")


def waive_command(v: dict, d: dict, role: str) -> str | None:
    """The `waive_cdc` / `waive_rdc` of one violation the review waived; None when the report does not say which objects it is about."""
    f = v.get("fields") or {}
    if role == "rdc":  # `report_rdc -list` says nothing else than the tag and the message
        msg = v.get("message", "").replace("{", "*").replace("}", "*")
        return f"waive_rdc -add W_{d['id']} -tag {v['tag']} -msg {{{_glob(msg)}}} -comment {{{_comment(d)}}}" if msg else None
    if v["tag"].startswith("CDC_COHERENCY") and f.get("ConvergencePoint"):
        sel = f'-filter {{ConvergencePoint == "{f["ConvergencePoint"]}"}}'
    elif f.get("SrcObject") and f.get("DestObject"):
        sel = f"-from {{{_glob(f['SrcObject'])}}} -to {{{_glob(f['DestObject'])}}}"
    else:
        return None
    return f"waive_cdc -add W_{d['id']} -tag {v['tag']} {sel} -comment {{{_comment(d)}}}"


# -- groups: violations of one kind, one decision and one waiver -----------------------------------------------------------------------
# A group is violations with the same tag that differ in ONE piece of what a waiver names (RDC: one word of the message, e.g. the source
# flop of 34 sources observed at the same destination; CDC: the -from or the -to object). The review decides a group once; the waiver
# script names it with one glob, written only when that glob matches exactly the group's violations in the whole report.

def _pieces(v: dict, role: str) -> list[str] | None:
    """What a waiver names, in pieces (RDC: the message split at the spaces, the spaces kept; CDC: from, to); None: never grouped."""
    f = v.get("fields") or {}
    if role == "rdc":
        return re.split(r"(\s+)", v["message"]) if v.get("message") else None
    if v["tag"].startswith("CDC_COHERENCY") or not (f.get("SrcObject") and f.get("DestObject")):
        return None
    return [f["SrcObject"], f["DestObject"]]


def _lit(s: str, role: str) -> str:
    return _glob(s.replace("{", "*").replace("}", "*")) if role == "rdc" else _glob(s)


def varying(members: list[dict], role: str) -> int | None:
    """The one piece the members differ in (None: more than one, or nothing to group)."""
    parts = [_pieces(v, role) for v in members]
    if len(members) < 2 or any(p is None or len(p) != len(parts[0]) for p in parts):
        return None
    diff = [i for i in range(len(parts[0])) if len({p[i] for p in parts}) > 1]
    return diff[0] if len(diff) == 1 else None


def groups(violations: list[dict], role: str) -> list[list[dict]]:
    """The violations in groups (largest first, each in the report's order; a violation of no group is a group of one), in the order of
    their first member."""
    left = list(violations)
    out: list[list[dict]] = []
    while True:
        cand: dict[tuple, list[dict]] = {}
        for v in left:
            p = _pieces(v, role)
            for i in range(len(p or [])):
                if not p[i].isspace():
                    cand.setdefault((v["tag"], len(p), i, *p[:i], *p[i + 1:]), []).append(v)
        best = max((g for g in cand.values() if varying(g, role) is not None), key=len, default=None)
        if not best:
            break
        out.append(best)
        ids = {v["id"] for v in best}
        left = [v for v in left if v["id"] not in ids]
    out += [[v] for v in left]
    order = {v["id"]: n for n, v in enumerate(violations)}
    return sorted(out, key=lambda g: order[g[0]["id"]])


def _glob_re(glob: str) -> re.Pattern:
    """VC Static's glob as a regex: `*` any text, `\\x` the character x (as _glob writes `[`, `]`)."""
    out, i = "", 0
    while i < len(glob):
        c = glob[i]
        if c == "\\" and i + 1 < len(glob):
            out, i = out + re.escape(glob[i + 1]), i + 2
            continue
        out, i = out + (".*" if c == "*" else re.escape(c)), i + 1
    return re.compile(out + r"\Z", re.S)


def group_globs(members: list[dict], role: str) -> list[str] | None:
    """The waiver's globs of a group (RDC: [msg]; CDC: [from, to]): its pieces, the varying one as common prefix * common suffix.
    None when the group cannot be named by one glob (shortcut: a CDC object glob whose `*` would cross a `/` is not written —
    VC Static's -from/-to match was not checked for that; the -msg glob was, on OpenTitan PWM)."""
    i = varying(members, role)
    if i is None:
        return None
    parts = [_pieces(v, role) for v in members]
    vals = [p[i] for p in parts]
    pre = os.path.commonprefix(vals)
    suf = os.path.commonprefix([x[len(pre):][::-1] for x in vals])[::-1]
    if role == "cdc" and any("/" in x[len(pre):len(x) - len(suf)] for x in vals):
        return None
    pieces = [_lit(x, role) for x in parts[0]]
    pieces[i] = _lit(pre, role) + "*" + _lit(suf, role)
    return ["".join(pieces)] if role == "rdc" else pieces


def _matches(globs: list[str], v: dict, role: str) -> bool:
    p = _pieces(v, role)
    if p is None:
        return False
    names = ["".join(p)] if role == "rdc" else p
    return all(_glob_re(g).match(n) for g, n in zip(globs, names))


def group_command(members: list[dict], d: dict, role: str, report: list[dict]) -> str | None:
    """The one `waive_*` of a waived group; None when its glob would also match a violation outside the group (it would waive more
    than the review decided) or no glob names it: the members are then waived one by one."""
    globs = group_globs(members, role)
    if not globs:
        return None
    ids = {v["id"] for v in members}
    tag = members[0]["tag"]
    if any(_matches(globs, v, role) != (v["id"] in ids) for v in report if v["tag"] == tag):
        return None
    sel = f"-msg {{{globs[0]}}}" if role == "rdc" else f"-from {{{globs[0]}}} -to {{{globs[1]}}}"
    first, last = members[0]["id"], members[-1]["id"]
    return f"waive_{role} -add W_{first}_{len(members)} -tag {tag} {sel} -comment {{{len(members)} violations {first}..{last}: {_comment(d)}}}"


def waive_tcl(violations: list[dict], items: list[dict], rtl: str, role: str) -> tuple[str, list[str]]:
    """(the script, the ids it cannot express). Only `waive` decisions: a fix, a constraint or a question stays an error. The waived
    violations of one group get one glob waiver (group_command), the others one each."""
    by_id = {v["id"]: v for v in violations}
    dec = {d["id"]: d for d in items}
    lines, skipped = [f"# {role.upper()} waivers of the review (Q3TUI {role}_waivers), RTL {rtl}: sourced after check_{role}"], []
    skipped += [d["id"] for d in items if d["action"] == "waive" and d["id"] not in by_id]
    waived = [v for v in violations if dec.get(v["id"], {}).get("action") == "waive"]
    for g in groups(waived, role):
        cmd = group_command(g, dec[g[0]["id"]], role, violations) if len(g) > 1 else None
        if cmd:
            lines.append(cmd)
            continue
        for v in g:
            one = waive_command(v, dec[v["id"]], role)
            lines.append(one) if one else skipped.append(v["id"])
    return "\n".join(lines) + "\n", skipped


def knowledge(builtin: Path, config_dir: Path, role: str) -> str:
    """The cases the review applies: the flow's (`<step>/md/knowledge.md`, K1…) then the project's (`config/sanity/<role>_knowledge.md`, U1…: they win)."""
    parts = []
    for label, f in (("Built-in knowledge", builtin), ("Project knowledge (wins over the built-in cases)", config_dir / "sanity" / f"{role}_knowledge.md")):
        if f.is_file() and f.read_text(errors="replace").strip():
            parts.append(f"## {label}\n\n{f.read_text(errors='replace').strip()}")
    return "\n\n".join(parts) or f"(no {role.upper()} knowledge: waive only what you can fully justify from the RTL, the SDC and the spec; ask otherwise)"


def handoff_text(role: str, d: dict, v: dict) -> tuple[str, str]:
    """(step of the owning flow, change-request text) for one `fix_rtl` / `spec` decision."""
    what = f"{role.upper()} {v['tag']}: {v['message'][:160]}"
    if len(d.get("members") or []) > 1:  # (one request for the group: its other violations are the same kind)
        what += f" (and {len(d['members']) - 1} more of the same kind: {', '.join(d['members'][1:])[:200]})"
    if d["action"] == "fix_rtl":
        return "rtl", (f"[rtl:{d['module']}] {what} — {d['change']}. Evidence: {d['reason']} "
                       "Keep the behaviour, the ports and every requirement tag unchanged; lint stays clean.")
    return "spec", (f"{what} — the spec must say: {d['change']}. Context: {d['reason']} Change only the requirements this affects (the RTL is updated "
                    "from those requirements module by module: do not reword or restructure the rest of the spec).")
