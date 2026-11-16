"""TUI panels of the ASIC flow's step kinds (the flow's `panels.py`; docs/spec/asic-flow.md): the port findings, the memory macros,
the synthesis numbers and the equivalence result. The SDC editor is the FPGA flow's (the same files). Edits go through the flow's actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.binding import Binding

from q3tui.flows.fpga import panels as fpga_panels
from q3tui.tui.panels import register_panel
from q3tui.tui.vlsit_panels import DataTab, TabSpec, VlsitPanel, artifact

if TYPE_CHECKING:
    from q3tui.pipeline.base import StepDef
    from q3tui.tui.app import Q3TUIApp

OK, BAD = Text("pass", style="green"), Text("fail", style="red")


def _status(v: str) -> Text:
    return Text(v, style={"pass": "green", "fail": "red", "warn": "yellow"}.get(v, "grey50"))


# -- ASIC port findings ---------------------------------------------------------------------------------------------


def _port_rows(app: "Q3TUIApp") -> list[tuple]:
    rows = []
    for f in (artifact(app, "asic_port.json", {}) or {}).get("findings", []):
        sent = f.get("handed_off")
        rows.append((f["id"], f["id"], Text(f["severity"], style="red" if f["severity"] == "error" else "yellow"), f["rule"],
                     f"{f['module']}:{f['line']}", f["text"][:70], Text(f"→ {sent['flow']}:{sent['step']}", style="green") if sent else Text("not yet", style="yellow")))
    return rows


def _port_detail(app: "Q3TUIApp", key: str) -> str:
    from q3tui.flows.asic.lib.port import RULES

    f = next((x for x in (artifact(app, "asic_port.json", {}) or {}).get("findings", []) if x["id"] == key), None)
    if f is None:
        return ""
    return f"**{f['id']}** — {RULES[f['rule']].title}\n\n`{f['file']}:{f['line']}` (module `{f['module']}`)\n\n```systemverilog\n{f['text']}\n```\n\n**Fix:** {f['fix']}"


class PortTab(DataTab):
    """The findings: h hands every finding not sent yet (or the highlighted one: H) to the flow that owns the RTL."""

    BINDINGS = [Binding("h", "handoff", "Hand off all"), Binding("H", "handoff_one", "Hand off this")]

    def _hand(self, ids: str) -> None:
        app = self.capp
        try:
            app.log_info(app.ops.run_action("asic_handoff", ids=ids))
        except Exception as exc:  # noqa: BLE001
            self.notify_error(exc)
            app.refresh_all()
            return
        app.refresh_all()
        step = next((s for s in app.engine.steps if s.kind == "asic.asic_port"), None)
        app.action_switch_flow(str((step.options if step else {}).get("handoff_flow") or "rtl"))

    def action_handoff(self) -> None:
        self._hand("")

    def action_handoff_one(self) -> None:
        key = self.current_key()
        if key:
            self._hand(key)


# -- memory macros ---------------------------------------------------------------------------------------------------------


def _macro_rows(app: "Q3TUIApp") -> list[tuple]:
    rows = []
    for name, w in sorted(((artifact(app, "asic_macro.json", {}) or {}).get("wrappers") or {}).items()):
        how = w.get("how", "?")
        chk = (w.get("check") or {}).get("status", "–") if w.get("asic_file") else "–"
        rows.append((name, name, Text(how, style="green" if how in ("macros", "compiled") else "yellow"), w.get("macro") or (w.get("why") or "")[:60],
                     f"{w['rows']} x {w['cols']}" if w.get("asic_file") else "", f"{w.get('area_um2'):g}" if w.get("asic_file") else "",
                     Text(chk, style={"pass": "green", "fail": "red"}.get(chk, "grey50"))))
    return rows


def _macro_detail(app: "Q3TUIApp", key: str) -> str:
    d = artifact(app, "asic_macro.json", {}) or {}
    w = (d.get("wrappers") or {}).get(key)
    if w is None:
        return ""
    s = w.get("spec") or {}
    ports = "; ".join(f"{p['kind']}: {p.get('addr')}" + (f", be {p['be']}" if p.get("be") else "") for p in s.get("ports", []))
    lines = [f"**{key}** (`{w['file']}`) — {s.get('words', '?')} x {s.get('bits', '?')}" + (f", ports {ports}" if ports else ""),
             f"PDK `{d.get('pdk_root')}`, corner `{d.get('corner') or 'any'}`, clock {d.get('period_ns') or '–'} ns, {d.get('catalog', 0)} macros found"]
    if w.get("asic_file"):
        lines += [f"**{w['how']}**: {w['rows']} x {w['cols']} `{w['macro']}` = {w.get('area_um2')} µm²",
                  f"ASIC body `{w['asic_file']}`, library `{w.get('db') or '–'}`, model `{w.get('model') or '–'}`",
                  f"Check: {(w.get('check') or {}).get('status', '–')} {(w.get('check') or {}).get('why') or (w.get('check') or {}).get('log') or ''}"]
    else:
        lines.append(f"**flip-flops**: {w.get('why') or '–'}")
    if w.get("why") and w.get("asic_file"):
        lines.append(f"Not taken: {w['why']}")
    c = d.get("compiler") or {}
    if c:
        lines.append(f"Memory compiler: {'usable' if c.get('usable') else 'not usable'} — {c.get('reason', '')}" + (f" (mem_compile: `{c['cmd']}`)" if c.get("cmd") else ""))
    return "\n\n".join(lines)


# -- synthesis numbers --------------------------------------------------------------------------------------------------


def _synth(app: "Q3TUIApp") -> dict:
    return artifact(app, "asic_synth.json", {}) or {}


def _synth_rows(app: "Q3TUIApp") -> list[tuple]:
    d = _synth(app)
    if not d:
        return []
    a, t, p, v, tg = d.get("area", {}), d.get("timing", {}), d.get("power", {}), d.get("verdict", {}), d.get("targets", {})
    rows = [("lib", "Library", ", ".join(x.rsplit("/", 1)[-1] for x in d.get("library", [])), "", ""),
            ("slack", "Worst setup slack (ns)", f"{t.get('slack_ns')}", f"≥ {tg.get('min_slack_ns', 0)}", _status(v.get("timing", "n/a"))),
            ("fmax", "Expected Fmax (MHz)", ("≥ " if all(g.get("bound") == "at_least" for g in t.get("groups", [])) and t.get("groups") else "") + f"{t.get('fmax_mhz', '–')}", "target " + ", ".join(f"{g['target_mhz']:g}" for g in t.get("groups", [])),
             _status("n/a" if not t.get("fmax_mhz") else ("pass" if t["fmax_mhz"] >= max((g["target_mhz"] for g in t.get("groups", [])), default=0) else "fail"))),
            ("tns", "Total negative slack (ns)", f"{t.get('tns_ns', '–')}", "", ""),
            ("path", "Worst path", f"{t.get('startpoint', '')} → {t.get('endpoint', '')}", f"{t.get('logic_levels', '?')} levels", ""),
            ("area", "Area (µm²)", f"{a.get('total_um2')}", f"≤ {tg['max_area_um2']}" if tg.get("max_area_um2") else "", _status(v.get("area", "n/a"))),
            ("cells", "Cells / sequential", f"{a.get('cells')} / {a.get('sequential_cells')}", "", ""),
            ("power", "Power (µW)", f"{p.get('total_uw', '–')}", f"dynamic {p.get('dynamic_uw', '–')}, leakage {p.get('leakage_uw', '–')}", ""),
            ("viol", "Constraint violations", str(d.get("violation_count", 0)) + (f" (+{d['waived_count']} waived)" if d.get("waived_count") else ""), "",
             _status(v.get("constraints", "n/a")))]
    for k, n in (d.get("check_design") or {}).items():
        open_ = sum(e["count"] for c, e in (d.get("warnings") or {}).items() if not e.get("waived")) if d.get("warnings") is not None else n
        rows.append((f"cd_{k}", f"check_design / log: {k}s", f"{n}" + (f" ({open_} not waived)" if open_ != n else ""), "",
                     Text("look", style="yellow") if open_ else Text("waived", style="green")))
    for i, w in enumerate(d.get("unconstrained") or []):
        rows.append((f"ct_{i}", "check_timing", w[:80], "", Text("look", style="yellow")))
    return rows


def _synth_detail(app: "Q3TUIApp", key: str) -> str:
    d = _synth(app)
    rep = app.project.asic_dir / "reports"
    name = {"fmax": "qor.rpt", "slack": "timing.rpt", "path": "timing.rpt", "tns": "qor.rpt", "area": "area.rpt", "cells": "area.rpt", "power": "power.rpt",
            "viol": "constraints.rpt"}.get(key) or ("check_design.rpt" if key.startswith("cd_") else "check_timing.rpt" if key.startswith("ct_") else "")
    f = rep / name if name else None
    if f is not None and f.is_file():
        return f"`build/syn/asic/reports/{name}`\n\n```\n{f.read_text(errors='replace')[:6000]}\n```"
    return f"Overall: **{d.get('verdict', {}).get('overall', '?')}** — Design Compiler, no placement or routing."


# -- waivers of the synthesis report --------------------------------------------------------------------------------------


_WAIVER_CACHE: dict = {}


def _waiver_data(app: "Q3TUIApp") -> dict:
    """The synthesis JSON with its waivable groups and codes (read from the reports, with today's waivers, when the run is older than
    the waivers or the waivers changed since: the tab is right before the next run)."""
    from q3tui.flows.asic.lib import waivers

    d = _synth(app)
    if not d:
        return d
    rep = app.project.build_dir / "syn" / "asic" / "reports"
    files = [rep / "constraints.rpt", rep / "check_design.rpt", waivers.path(app.project), *([app.project.root / d["log"]] if d.get("log") else [])]
    stamp = tuple(f.stat().st_mtime_ns if f.is_file() else 0 for f in files) + (id(d),)
    if _WAIVER_CACHE.get("stamp") != stamp:  # (the reports are parsed again only when one of them, the waivers or the JSON changed)
        _WAIVER_CACHE.update(stamp=stamp, data=waivers.from_reports(app.project, d))
    return _WAIVER_CACHE["data"]


def _waiver_rows(app: "Q3TUIApp") -> list[tuple]:
    from q3tui.flows.asic.lib import waivers

    by_key = {w["key"]: w for w in waivers.load(app.project)}
    rows = []
    for r in waivers.report_items(_waiver_data(app)):
        w = by_key.get(r["key"])
        state = Text(f"waived: {w['reason'][:40]}", style="green") if w and r["open"] == 0 else \
            Text(f"{r['open']} open (waiver up to {w.get('max_ns')} ns)", style="red") if w else Text("open", style="yellow" if r["what"] == "code" else "red")
        rows.append((r["key"], r["title"], str(r["count"]), "" if r["worst_ns"] is None else f"{r['worst_ns']:g}", state))
    for k, w in by_key.items():  # (single violations waived by key: shown so they can be removed)
        if w.get("what") == "item":
            rows.append((k, f"violation {k}", "1", "", Text(f"waived: {w['reason'][:40]}", style="green")))
    return rows


def _waiver_detail(app: "Q3TUIApp", key: str) -> str:
    from q3tui.flows.asic.lib import waivers

    r = next((x for x in waivers.report_items(_waiver_data(app)) if x["key"] == key), None)
    w = next((x for x in waivers.load(app.project) if x["key"] == key), None)
    lines = [f"**{key}**" + (f" — {r['count']} in the report" + (f", worst {r['worst_ns']:g} ns" if r and r["worst_ns"] is not None else "") if r else "")]
    if r and r.get("sample"):
        lines.append(f"```\n{r['sample']}\n```")
    if w:
        lines.append(f"Waived ({w.get('at', '')}): {w['reason']}" + (f" — up to {w['max_ns']:g} ns" if w.get("max_ns") is not None else ""))
    lines.append("`w` waive (a timing group: up to its worst violation now) · `u` remove the waiver · one violation: action `asic_waive` with "
                 "what=item, key=<group>:<endpoint>")
    return "\n\n".join(lines)


class WaiverTab(DataTab):
    """The report's constraint groups and warning codes: w waives the highlighted one with a reason, u removes its waiver."""

    BINDINGS = [Binding("w", "waive", "Waive"), Binding("u", "unwaive", "Remove waiver")]

    def action_waive(self) -> None:
        from q3tui.flows.asic.lib import waivers
        from q3tui.tui.screens import TextPromptScreen

        key = self.current_key()
        r = next((x for x in waivers.report_items(_waiver_data(self.capp)) if x["key"] == key), None)
        if r is None:
            return
        cap = -r["worst_ns"] if r["what"] == "group" and r["worst_ns"] is not None and r["worst_ns"] < 0 else None

        def done(reason: str | None) -> None:
            if reason is None:
                return
            try:
                self.capp.log_info(self.capp.ops.run_action("asic_waive", what=r["what"], key=key, reason=reason,
                                                            max_ns="" if cap is None else str(cap)))
            except Exception as exc:  # noqa: BLE001
                self.notify_error(exc)
            self.capp.refresh_all()

        self.capp.push_screen(TextPromptScreen(f"Waive {r['title']}", body=f"{r['count']} in the report" + (f", up to {cap:g} ns" if cap else "")
                                               + ". Why is it fine?", value="fixed in physical design" if r["key"].startswith("min_delay") else "",
                                               multiline=False), done)

    def action_unwaive(self) -> None:
        key = self.current_key()
        if not key:
            return
        try:
            self.capp.log_info(self.capp.ops.run_action("asic_unwaive", key=key))
        except Exception as exc:  # noqa: BLE001
            self.notify_error(exc)
        self.capp.refresh_all()


# -- equivalence check ---------------------------------------------------------------------------------------------------


def _lec_rows(app: "Q3TUIApp") -> list[tuple]:
    d = artifact(app, "asic_lec.json", {}) or {}
    if not d:
        return []
    st = d.get("status", "unknown")
    return [("status", "Result", st.replace("_", " "), "", _status("pass" if st == "equivalent" else "fail")),
            ("pass", "Passing compare points", str(d.get("passing", "–")), "", ""), ("fail", "Failing compare points", str(d.get("failing", "–")), "", ""),
            ("nl", "Netlist", d.get("netlist") or "", "", "")]


def _lec_detail(app: "Q3TUIApp", key: str) -> str:
    f = app.project.asic_dir / "reports" / "lec.rpt"
    return f"```\n{f.read_text(errors='replace')[:6000]}\n```" if f.is_file() else "_no lec.rpt yet_"


def _tabs_for(kind: str) -> tuple[TabSpec, ...]:
    if kind == "asic.sdc":
        return fpga_panels._tabs_for("fpga.sdc")
    if kind == "asic.asic_port":
        return (TabSpec("port", "Findings", ("Id", "Severity", "Rule", "Where", "Code", "Handed off"), _port_rows, _port_detail,
                        "h hand every finding to the flow that owns the RTL (H: the highlighted one) — then run that flow to apply them",
                        widget=PortTab, empty="no findings (or not run yet — r)"),)
    if kind == "asic.asic_macro":
        return (TabSpec("macros", "Macros", ("Wrapper", "How", "Macro", "Grid", "Area (µm²)", "Check"), _macro_rows, _macro_detail,
                        "the memory wrappers as PDK macros; Settings (,) → asic_macro: PDK folder, corner, source; flops: [wrappers] keeps flip-flops",
                        empty="no memory wrapper (*_sram / *_rf / *_rom), or not run yet — r"),)
    if kind == "asic.asic_synth":
        return (TabSpec("qor", "QoR", ("Item", "Value", "Target", "Status"), _synth_rows, _synth_detail,
                        "set the library in Settings (,) → asic_synth; targets: min_slack_ns, max_area_um2", empty="no asic_synth.json yet — run (r)"),
                TabSpec("waivers", "Waivers", ("What", "Count", "Worst (ns)", "State"), _waiver_rows, _waiver_detail,
                        "w waive the highlighted group / warning with a reason, u remove it — then r: the report is scored again (no synthesis)",
                        widget=WaiverTab, empty="nothing to waive (or not run yet — r)"))
    if kind == "asic.asic_lec":
        return (TabSpec("lec", "LEC", ("Item", "Value", "", "Status"), _lec_rows, _lec_detail, "Formality: RTL against the netlist", empty="no result yet — run (r)"),)
    return ()


def _builder(kind: str):
    def build(step: "StepDef"):
        return VlsitPanel(step, _tabs_for(kind))

    return build


for _kind in ("asic.sdc", "asic.asic_port", "asic.asic_macro", "asic.asic_synth", "asic.asic_lec"):
    register_panel(_kind, _builder(_kind))
