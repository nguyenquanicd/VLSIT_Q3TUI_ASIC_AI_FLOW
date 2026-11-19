"""TUI panels of the ECO flow's steps (the flow's `panels.py`; docs/spec/eco-flow.md). Every step gets two tabs before Files / Questions:

- **Report**: the step's result as rows (item, value, a coloured status), the highlighted row's detail on the right (the requirement, the spec /
  RTL diff, the netlist patch, the Formality / PrimeTime report, …);
- **ECO**: the whole flow at a glance, one row per step (its result in one line), the detail of the highlighted step.

Everything is read from the step artifacts (`schemas/eco_*.json`, `eco/`): a step that has not run shows "not run yet"."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING

from rich.text import Text

from q3tui.core.icons import icon
from q3tui.tui.panels import register_panel
from q3tui.tui.vlsit_panels import TabSpec, VlsitPanel, artifact, read_artifact

if TYPE_CHECKING:
    from q3tui.pipeline.base import StepDef
    from q3tui.tui.app import Q3TUIApp

DETAIL_CHARS = 12000  # (a report longer than this is cut in the detail pane: the full file is in the Files tab)
_LOOK = {"pass": ("pass", "pass", "green"), "fail": ("fail", "fail", "red"), "warn": ("stale", "check", "yellow"),
         "skip": ("na", "skipped", "grey50"), "wait": ("pending", "waiting", "cyan"), "info": ("arrow", "", "grey50")}


def _st(kind: str, word: str = "") -> Text:
    """A coloured status cell: icon + word (`kind`: pass / fail / warn / skip / wait / info)."""
    glyph, default, style = _LOOK.get(kind, _LOOK["info"])
    if not (word or default):
        return Text("")
    return Text(f"{icon(glyph)} {word or default}", style=style)


def _one_line(s, n: int = 50) -> str:  # (a longer value pushes the Status column out of the pane: the full text is in the detail)
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _file(app: "Q3TUIApp", rel) -> str | None:
    if not rel:
        return None
    p = app.project.root / str(rel)
    try:
        return p.read_text(errors="replace") if p.is_file() else None
    except OSError:
        return None


def _code(text: str | None, lang: str = "text", what: str = "") -> str:
    if text is None:
        return f"_{what or 'the file'} is not there (yet)_"
    cut = f"\n\n_… cut at {DETAIL_CHARS} characters: the full file is in the Files tab_" if len(text) > DETAIL_CHARS else ""
    return f"```{lang}\n{text[:DETAIL_CHARS].rstrip()}\n```{cut}"


def _report(app: "Q3TUIApp", rel, lang: str = "text") -> str:
    """A report file as the detail: Markdown as it is, the rest as a code block."""
    text = _file(app, rel)
    if text is not None and str(rel).endswith(".md"):
        return text[:DETAIL_CHARS]
    return f"**`{rel}`**\n\n{_code(text, lang, f'`{rel}`')}"


def _diff_stat(text: str | None) -> str:
    if not text:
        return "no change"
    lines = text.splitlines()
    files = [ln[6:] for ln in lines if ln.startswith("+++ b/")]
    add = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    rem = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    return f"{len(files)} file(s), +{add} −{rem}"


def _eq_kind(status: str | None) -> str:
    return {"equivalent": "pass", "skipped": "skip", None: "info"}.get(status, "fail")


NOT_RUN = ("not run yet", "info")


# -- eco_inputs -------------------------------------------------------------------------------------------------------


def _inputs(app):
    return artifact(app, "eco_inputs.json", {}) or {}


def _inputs_brief(app):
    d = _inputs(app)
    return (f"{d.get('mode', '?')} mode · top {d.get('top', '?')} · ORG in {d.get('ref', '?')}", "pass") if d else NOT_RUN


def _inputs_rows(app):
    d = _inputs(app)
    if not d:
        return []
    ref = read_artifact(app.project.root / "eco" / "ref.json", {}) or {}
    mode = d.get("mode", "?")
    exists = lambda rel: bool(rel) and (app.project.root / str(rel)).is_file()  # noqa: E731
    rows = [("mode", "Mode", "project — this project's RTL, spec updated, dv + Sanity" if mode == "project" else "external — fire-fighting, RTL only",
             _st("info", mode)),
            ("top", "Top module", d.get("top", "?"), _st("info")),
            ("ref", "ORG design kept in", f"{d.get('ref', '?')}/" + (f"  (since {ref['created'].replace('T', ' ')})" if ref.get("created") else ""), _st("pass", "kept")),
            ("req", "Requirement", d.get("requirement", "?"), _st("pass", "found") if exists(d.get("requirement")) else _st("fail", "missing"))]
    for key, label in (("rtl", "ORG RTL (filelist)"), ("org_netlist", "ORG netlist"), ("org_sdc", "ORG SDC"), ("org_svf", "ORG SVF (DC guidance)")):
        rel = d.get(key)
        ok = exists(rel)
        rows.append((key, label, rel or "–", _st("pass", "found") if ok else _st("warn" if key in ("org_sdc", "org_svf") else "fail", "missing")))
    return rows


def _inputs_detail(app, key):
    d = _inputs(app)
    if key == "req":
        return _file(app, d.get("requirement")) or "_no requirement file_"
    if key in ("rtl", "org_sdc"):
        return _report(app, d.get(key), "tcl" if key == "org_sdc" else "text")
    if key == "ref":
        return _report(app, "eco/ref.json", "json")
    if key == "org_netlist":
        text = _file(app, d.get(key)) or ""
        cells = Counter(m.group(1) for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]*BWP\w*|[A-Za-z_]\w*)\s+\\?\S+\s*\(", text, re.M)
                        if m.group(1) not in ("module", "input", "output", "wire", "assign"))
        top = "\n".join(f"| `{c}` | {n} |" for c, n in cells.most_common(15))
        return f"**`{d.get(key)}`** — {sum(cells.values())} instances\n\n| Cell | Count |\n|---|---|\n{top}\n"
    src = d.get("source") or {}
    return ("## Where the ORG design came from\n\n" + "\n".join(f"- {k}: `{v}`" for k, v in src.items()) +
            f"\n\n## Hashes (a change re-runs the ECO)\n\n" + "\n".join(f"- {k}: `{v[:16]}…`" for k, v in (d.get("sha256") or {}).items()))


# -- eco_eq1 / eco_eq2 --------------------------------------------------------------------------------------------------


def _eq(app, n):
    return artifact(app, f"eco_eq{n}.json", {}) or {}


def _eq_brief(n):
    def brief(app):
        d = _eq(app, n)
        if not d:
            return NOT_RUN
        st = d.get("status")
        how = " (asic_lec reused)" if d.get("source") == "asic_lec" else ""
        return f"{(st or '?').replace('_', ' ')} · {d.get('passing', '–')} compare points{how}", _eq_kind(st)
    return brief


def _eq_rows(n):
    def rows(app):
        d = _eq(app, n)
        if not d:
            return []
        st = d.get("status")
        out = [("status", "Result", (st or "?").replace("_", " "), _st(_eq_kind(st)))]
        if n == 1:
            out.append(("src", "Checked by", {"asic_lec": "asic_lec result reused (same ORG RTL + netlist)", "formality": "Formality, this step",
                                              "you": "nobody — skipped by your answer"}.get(d.get("source"), d.get("source", "?")), _st("info")))
        out.append(("pass", "Passing compare points", str(d.get("passing", "–")), _st("info")))
        for key, label in (("failing", "Failing compare points"), ("unmatched", "Unmatched points")):
            if key in d:
                v = d.get(key) or 0
                out.append((key, label, str(v), _st("pass", "none") if not v else _st("fail", str(v))))
        if d.get("report"):
            out.append(("rpt", "Formality report", d["report"], _st("info")))
        adv = d.get("advice") or {}
        if adv.get("summary"):
            out.append(("advice", "Why (AI advice)", _one_line(adv["summary"]), _st("warn", "read")))
        for i, (q, a) in enumerate((d.get("asks") or {}).items()):
            out.append((f"ask{i}", f"Question {q}", _one_line(a, 70), _st("info")))
        return out
    return rows


def _eq_detail(n):
    def detail(app, key):
        d = _eq(app, n)
        if key == "rpt":
            return _report(app, d.get("report"))
        md = _file(app, f"eco/reports/eq{n}.md")
        if md:
            return md[:DETAIL_CHARS]
        if d.get("source") == "asic_lec":
            return ("## EQ(1) = the asic flow's LEC\n\nThe ORG RTL and the ORG netlist are the files `asic_lec` proved equivalent, so its "
                    f"result stands for EQ(1).\n\n{_report(app, d.get('report'))}")
        return _report(app, d.get("report")) if d.get("report") else "_no report yet_"
    return detail


# -- eco_spec / eco_rtl -------------------------------------------------------------------------------------------------


def _change_brief(name, diff_rel):
    def brief(app):
        d = artifact(app, f"{name}.json", {}) or {}
        if not d:
            return NOT_RUN
        if d.get("status") == "skipped":
            return "skipped (external RTL: no spec)", "skip"
        n = len(d.get("concerns") or [])
        return f"{_diff_stat(_file(app, diff_rel))}" + (f" · {n} concern(s)" if n else ""), "warn" if n else "pass"
    return brief


def _change_rows(name, diff_rel):
    def rows(app):
        d = artifact(app, f"{name}.json", {}) or {}
        if not d:
            return []
        if d.get("status") == "skipped":
            return [("status", "Result", "skipped: external RTL (fire-fighting ECO), the spec is not updated", _st("skip"))]
        diff = _file(app, diff_rel)
        st = d.get("status", "updated" if diff else "unchanged")
        out = [("status", "Result", f"{st} — {_diff_stat(diff)}", _st("pass" if diff else "warn", st)),
               ("summary", "Summary", _one_line(d.get("summary")), _st("info")),
               ("diff", "Diff vs ORG (ref/)", diff_rel, _st("info", f"{d.get('diff_lines', '?')} lines"))]
        if d.get("change"):
            out.append(("plan", "Planned change", _one_line(d["change"]), _st("info")))
        out += [(f"c{i}", f"Change · {c.get('file', '?').rsplit('/', 1)[-1]}", _one_line(c.get("what")), _st("pass", "done"))
                for i, c in enumerate(d.get("changes") or [])]
        out += [(f"k{i}", "Concern", _one_line(c), _concern_status(d, c)) for i, c in enumerate(d.get("concerns") or [])]
        return out
    return rows


def _concern_ask(d: dict, concern: str) -> tuple[str | None, dict]:
    """(the question id, its record) a concern of the last change was asked as (lib/base.py ask_concerns), or (None, {})."""
    return next(((q, a) for q, a in reversed(list((d.get("concern_asks") or {}).items())) if a.get("concern") == concern), (None, {}))


def _concern_status(d: dict, concern: str):
    qid, a = _concern_ask(d, concern)
    if not qid:
        return _st("warn", "read")
    if not a.get("used"):
        return _st("wait", f"answer {qid}")
    return _st("pass", "kept") if str(a.get("answer", "")).lower().startswith("keep") else _st("info", "sent back")


def _hunks(diff: str, file: str) -> str:
    """The part of a unified diff about one file."""
    parts = re.split(r"(?m)^(?=--- )", diff)
    mine = [p for p in parts if re.search(rf"(?m)^\+\+\+ b/{re.escape(file)}\s*$", p)]
    return "".join(mine) or diff


def _change_detail(name, diff_rel):
    def detail(app, key):
        d = artifact(app, f"{name}.json", {}) or {}
        diff = _file(app, diff_rel)
        body = _code(diff, "diff", f"`{diff_rel}`") if diff else "_no difference from the ORG design_"
        if key == "summary":
            return f"## Summary\n\n{d.get('summary', '')}\n\n## Diff\n\n{body}"
        if key == "plan":
            return f"## Planned change\n\n{d.get('change', '')}\n\n## Diff\n\n{body}"
        if key.startswith("c") and key[1:].isdigit():
            c = (d.get("changes") or [])[int(key[1:])]
            return f"## `{c.get('file')}`\n\n{c.get('what', '')}\n\n{_code(_hunks(diff or '', c.get('file', '')), 'diff') if diff else ''}"
        if key.startswith("k") and key[1:].isdigit():
            c = (d.get("concerns") or [])[int(key[1:])]
            qid, a = _concern_ask(d, c)
            how = (f"_Asked as {qid} (Questions tab): keep the change, or type what to change._" if qid and not a.get("used")
                   else f"_Your answer to {qid}:_ {a.get('answer')}" if qid
                   else "_Not asked (auto-answer kept the change); check whether this needs a follow-up._")
            return f"## Concern\n\n{c}\n\n{how}"
        return f"**`{diff_rel}`** — {_diff_stat(diff)}\n\n{body}"
    return detail


# -- eco_verify ---------------------------------------------------------------------------------------------------------

_VERIFY_KIND = {"passed": "pass", "skipped": "skip", "waiting": "wait", "fixes": "warn", "failed": "fail"}


def _verify(app):
    return artifact(app, "eco_verify.json", {}) or {}


def _verify_brief(app):
    d = _verify(app)
    if not d:
        return NOT_RUN
    fl = d.get("flows") or {}
    parts = [f"{k} {'pass' if v.get('passed') else 'FAIL'}" for k, v in fl.items()]
    return (" · ".join(parts) or d.get("status", "?")), _VERIFY_KIND.get(d.get("status"), "info")


def _verify_rows(app):
    d = _verify(app)
    if not d:
        return []
    st = d.get("status", "?")
    out = [("status", "Result", {"passed": "dv and Sanity passed on the ECO'd RTL", "skipped": "skipped (fire-fighting ECO or your answer)",
                                 "waiting": "waiting for your answer (Questions tab)", "fixes": "dv / Sanity asked for an RTL fix: eco_rtl runs again",
                                 "failed": "dv / Sanity did not pass"}.get(st, st), _st(_VERIFY_KIND.get(st, "info"), st))]
    for k, v in (d.get("flows") or {}).items():
        out.append((k, {"dv": "Verification (dv)", "sanity": "Sanity (CDC / RDC)"}.get(k, k), _one_line(v.get("note")),
                    _st("pass") if v.get("passed") else _st("fail")))
    return out


def _verify_detail(app, key):
    if key == "dv":
        res = artifact(app, "dv_test_results.json", {}) or {}
        tests = res.get("tests") or res.get("results") or []
        rows = "\n".join(f"| {t.get('id', t.get('name', '?'))} | {t.get('name', '')} | {'✔' if t.get('status') == 'PASS' else '✖'} {t.get('status', '?')} |"
                         for t in tests)
        cnt = Counter(t.get("status") for t in tests)
        return (f"## dv on the ECO'd RTL — {', '.join(f'{n} {s}' for s, n in cnt.items()) or 'no result'}\n\n| Test | Name | Status |\n|---|---|---|\n{rows}\n"
                if tests else _report(app, "reports/dv_test_results.md"))
    if key == "sanity":
        return "\n\n".join(x for x in (_file(app, "reports/cdc_report.md"), _file(app, "reports/rdc_report.md")) if x)[:DETAIL_CHARS] or "_no Sanity report_"
    d = _verify(app)
    return "## Why this step\n\nIn project mode the ECO'd RTL goes through the same verification as the original: dv (the testbench, " \
           "updated for the ECO) and Sanity (CDC / RDC). An RTL fix they need goes back to eco_rtl, as a minimal change.\n\n" + \
           "\n".join(f"- **{k}**: {v.get('note', '')}" for k, v in (d.get("flows") or {}).items())


# -- eco_patch ----------------------------------------------------------------------------------------------------------


def _patch(app):
    d = artifact(app, "eco_patch.json", {}) or {}
    text = _file(app, d.get("file") or "eco/patch/eco_patch.tcl") if d else None
    cmds = [ln.strip() for ln in (text or "").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return d, text, cmds


def _patch_brief(app):
    d, _, cmds = _patch(app)
    if not d:
        return NOT_RUN
    cells = [c for c in cmds if c.startswith("create_cell")]
    return f"{len(cmds)} commands · {len(cells)} new cell(s)", "pass"


def _patch_rows(app):
    d, _, cmds = _patch(app)
    if not d:
        return []
    by = Counter(c.split()[0] for c in cmds)
    types = Counter(c.split()[-1].rsplit("/", 1)[-1] for c in cmds if c.startswith("create_cell"))
    rows = [("cmds", "Netlist edits", f"{len(cmds)} commands", _st("pass", "checked")),
            ("cells", "New cells", ", ".join(f"{n}× {t}" for t, n in types.most_common()) or "none", _st("info", str(sum(types.values())))),
            ("nets", "New nets", str(by.get("create_net", 0)), _st("info")),
            ("conn", "Connections", f"{by.get('connect_net', 0)} connect · {by.get('disconnect_net', 0)} disconnect", _st("info"))]
    other = {k: v for k, v in by.items() if k not in ("create_cell", "create_net", "connect_net", "disconnect_net")}
    if other:
        rows.append(("other", "Other edits", ", ".join(f"{v}× {k}" for k, v in other.items()), _st("info")))
    if d.get("notes"):
        rows.append(("notes", "How it works (AI notes)", _one_line(d["notes"]), _st("info", "read")))
    rows.append(("file", "Patch file", d.get("file", "eco/patch/eco_patch.tcl"), _st("info")))
    return rows


def _patch_detail(app, key):
    d, text, cmds = _patch(app)
    if key == "notes":
        return "## How the patch works\n\n" + "\n\n".join(s.strip() for s in re.split(r"(?<=\.)\s+(?=[A-Z])", d.get("notes", ""))) + "\n"
    if key == "cells":
        made = [c for c in cmds if c.startswith("create_cell")]
        return "## New cells\n\n" + _code("\n".join(made), "tcl")
    return f"**`{d.get('file', 'eco/patch/eco_patch.tcl')}`** — run by eco_apply in Design Compiler (allow-listed commands only)\n\n" + _code(
        "\n".join(cmds), "tcl")


# -- eco_apply ----------------------------------------------------------------------------------------------------------


def _apply(app):
    return artifact(app, "eco_apply.json", {}) or {}


def _apply_brief(app):
    d = _apply(app)
    if not d:
        return NOT_RUN
    return (f"Post NETLIST written: {d.get('netlist', '?')}", "pass") if d.get("status") == "pass" else (
        f"failed: {len(d.get('errors') or [])} error(s)", "fail")


def _apply_rows(app):
    d = _apply(app)
    if not d:
        return []
    ok = d.get("status") == "pass"
    errs = d.get("errors") or []
    cd = _file(app, "eco/reports/apply_check_design.rpt") or ""
    warns = len(re.findall(r"(?m)^\s*Warning:", cd))
    rows = [("status", "Result", "the patch applied, no compile (only the edited cells changed)" if ok else "Design Compiler stopped on the patch",
             _st("pass" if ok else "fail", d.get("status", "?"))),
            ("net", "Post NETLIST", d.get("netlist", "–"), _st("pass", "written") if ok else _st("fail", "none")),
            ("err", "Errors", str(len(errs)), _st("pass", "none") if not errs else _st("fail", str(len(errs)))),
            ("cd", "check_design warnings", str(warns), _st("pass", "none") if not warns else _st("warn", str(warns)))]
    if d.get("fixes"):
        rows.append(("fix", "Timing fixes applied (eco_sta)", str(len(d["fixes"])), _st("info")))
    rows.append(("log", "Design Compiler log", d.get("log", "eco/reports/apply_dc.log"), _st("info")))
    return rows


def _apply_detail(app, key):
    d = _apply(app)
    if key == "err":
        errs = d.get("errors") or []
        return "## Errors\n\n" + ("\n".join(f"- `{e}`" for e in errs) if errs else "_none_")
    if key == "log":
        return _report(app, d.get("log", "eco/reports/apply_dc.log"))
    if key == "fix":
        return "## Timing fixes applied\n\n" + "\n".join(f"- `{f}`" for f in d.get("fixes") or [])
    return _report(app, "eco/reports/apply_check_design.rpt")


# -- eco_sta ------------------------------------------------------------------------------------------------------------


def _sta(app):
    return artifact(app, "eco_sta.json", {}) or {}


def _sta_brief(app):
    d = _sta(app)
    if not d:
        return NOT_RUN
    s, h = d.get("setup") or {}, d.get("hold") or {}
    kind = {"pass": "pass", "fixing": "warn"}.get(d.get("status"), "fail")
    return f"setup {s.get('slack_ns', '?')} ns · hold {h.get('slack_ns', '?')} ns", kind


def _sta_rows(app):
    d = _sta(app)
    if not d:
        return []
    s, h = d.get("setup") or {}, d.get("hold") or {}
    st = d.get("status", "?")
    nsv, nhv = len(d.get("setup_violations") or []), len(d.get("hold_violations") or [])
    rows = [("status", "Verdict", {"pass": "timing met on the Post NETLIST", "fixing": "setup violated: timing fixes for eco_apply",
                                   "fail": "setup violated"}.get(st, st), _st({"pass": "pass", "fixing": "warn"}.get(st, "fail"), st)),
            ("setup", "Setup WNS", f"{s.get('slack_ns', '?')} ns   {s.get('startpoint', '?')} → {s.get('endpoint', '?')}",
             _st("pass", "met") if s.get("met") else _st("fail", "violated")),
            ("hold", "Hold WNS", f"{h.get('slack_ns', '?')} ns   {h.get('startpoint', '?')} → {h.get('endpoint', '?')}",
             _st("pass", "met") if h.get("met") else _st("warn", "violated (pre-layout)")),
            ("viol", "Violations", f"{nsv} setup · {nhv} hold", _st("pass", "none") if not nsv + nhv else _st("fail" if nsv else "warn", str(nsv + nhv)))]
    if d.get("fixes"):
        rows.append(("fix", "Timing fixes", str(len(d["fixes"])), _st("info")))
    rows.append(("check", "check_timing", "eco/reports/sta_check_timing.rpt", _st("info")))
    return rows


def _sta_detail(app, key):
    return {"setup": lambda: _report(app, "eco/reports/sta_setup.rpt"), "hold": lambda: _report(app, "eco/reports/sta_hold.rpt"),
            "viol": lambda: _report(app, "eco/reports/sta_constraints.rpt"), "check": lambda: _report(app, "eco/reports/sta_check_timing.rpt"),
            }.get(key, lambda: _report(app, "eco/reports/sta.md"))()


# -- the steps ----------------------------------------------------------------------------------------------------------

# step: (title of the ECO tab row, brief, rows, detail, hint)
STEPS: dict[str, tuple[str, Callable, Callable, Callable, str]] = {
    "eco_inputs": ("Inputs + ORG kept in ref/", _inputs_brief, _inputs_rows, _inputs_detail,
                   "the ORG design and the requirement; a new ECO: delete eco/ref.json, then reset (x)"),
    "eco_eq1": ("EQ(1) ORG RTL vs ORG netlist", _eq_brief(1), _eq_rows(1), _eq_detail(1), "Formality: the ORG netlist is the ORG RTL before anything changes"),
    "eco_spec": ("Spec updated", _change_brief("eco_spec", "eco/spec.diff"), _change_rows("eco_spec", "eco/spec.diff"),
                 _change_detail("eco_spec", "eco/spec.diff"), "the spec change for the requirement, against ref/ (project mode)"),
    "eco_rtl": ("RTL(F) minimal change", _change_brief("eco_rtl", "eco/rtl.diff"), _change_rows("eco_rtl", "eco/rtl.diff"),
                _change_detail("eco_rtl", "eco/rtl.diff"), "the smallest RTL change against the ORG RTL in ref/"),
    "eco_verify": ("dv + Sanity on RTL(F)", _verify_brief, _verify_rows, _verify_detail, "dv and Sanity must pass on the ECO'd RTL before the netlist ECO"),
    "eco_patch": ("Netlist patch (Tcl)", _patch_brief, _patch_rows, _patch_detail, "the netlist edits for the RTL change, checked against the allow-list"),
    "eco_apply": ("Post NETLIST (DC)", _apply_brief, _apply_rows, _apply_detail, "Design Compiler applies the patch to the ORG netlist, no compile"),
    "eco_eq2": ("EQ(2) RTL(F) vs Post NETLIST", _eq_brief(2), _eq_rows(2), _eq_detail(2), "Formality: the Post NETLIST is the ECO'd RTL"),
    "eco_sta": ("STA Post NETLIST (PT)", _sta_brief, _sta_rows, _sta_detail, "PrimeTime on the Post NETLIST with the ORG constraints"),
}


def _overview_rows(app):
    out = []
    for i, (name, (title, brief, *_)) in enumerate(STEPS.items(), 1):
        try:
            text, kind = brief(app)
        except Exception as exc:  # noqa: BLE001 - one broken artifact never hides the others
            text, kind = f"cannot read: {exc}", "warn"
        out.append((name, f"{i}", title, _one_line(text, 70), _st(kind)))
    return out


def _overview_summary(app) -> str:
    kinds = Counter()
    for _, brief, *_ in STEPS.values():
        try:
            kinds[brief(app)[1]] += 1
        except Exception:  # noqa: BLE001
            kinds["warn"] += 1
    done = kinds["pass"] + kinds["skip"] + kinds["warn"]
    return f"{done}/{len(STEPS)} steps done" + (f" · {kinds['fail']} failed" if kinds["fail"] else "") + (
        f" · {kinds['warn']} with notes to read" if kinds["warn"] else "") + (f" · {kinds['wait']} waiting" if kinds["wait"] else "") + (
        f" · {kinds['info']} not run" if kinds["info"] else "")


def _overview_detail(app, key):
    if key not in STEPS:
        return ""
    title, _, rows, detail, hint = STEPS[key]
    body = [f"| {label} | {str(value).replace('|', '/')} | {status.plain} |" for _, label, value, status in rows(app)]
    if not body:
        return f"## {title}\n\n_not run yet — select the step and run it (r)_"
    return "\n".join([f"## {title}", "", f"_{hint}_", "", "| Item | Value | Status |", "|---|---|---|", *body])


def _brief_summary(brief):
    def summary(app) -> str:
        return brief(app)[0]
    return summary


def _tabs_for(name: str) -> tuple[TabSpec, ...]:
    title, brief, rows, detail, hint = STEPS[name]
    return (TabSpec("report", "Report", ("Item", "Value", "Status"), rows, detail, hint, empty="not run yet — run (r)",
                    summary=_brief_summary(brief)),
            TabSpec("eco", "ECO", ("#", "Step", "Result", "Status"), _overview_rows, _overview_detail,
                    "the whole ECO flow; the highlighted step's result on the right", summary=_overview_summary))


def _builder(name: str):
    def build(step: "StepDef"):
        return VlsitPanel(step, _tabs_for(name))

    return build


for _name in STEPS:
    register_panel(f"eco.{_name}", _builder(_name))
