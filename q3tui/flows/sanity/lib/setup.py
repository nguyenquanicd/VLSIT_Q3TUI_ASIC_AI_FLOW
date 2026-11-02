"""The analysis environment of the Sanity flow (step `setup`, shared by CDC and RDC): the design intent the tool cannot infer — the resets (polarity,
asynchronous / synchronous), the modules that are black boxes (big memories, models), the quasi-static signals (configuration written once, then
held), the constants (test / mode pins tied in operation) and the design's own reset synchronizers.

An LLM stage decides it from the spec and the RTL (read only) with the facts code computes (the top's ports, the modules and their arrays, the SDC's
clocks and resets, the memory earlier runs needed); the answer is data (`schemas/sanity_setup.json`) and code writes the tool's commands
(`tcl`): `set_blackbox` before analyze; `create_reset`, `create_static`, `set_case_analysis`, `set_rdc_synchronizer` after the SDC. Code checks every
name against the RTL (`problems`) and, when the tool is there, an elaboration-only run of it (`dry_run`): what is wrong goes back to the LLM."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SETUP_JSON = "sanity_setup.json"


class SetupReset(BaseModel):
    port: str = Field(description="the reset input of the top (its port name)")
    active: Literal["low", "high"] = Field(description="the level that resets")
    kind: Literal["async", "sync"] = Field("async", description="async: it drives flops' asynchronous set / reset pins; sync: it is used as data (in the D logic)")
    reason: str = Field(description="the evidence: the spec section, or the RTL (file:line) that uses it")


class BlackBox(BaseModel):
    module: str = Field(description="the module (file name without extension)")
    clock: str = Field("", description="the SDC clock its data pins are synchronous to (empty: the design's only clock)")
    reason: str = Field(description="why only its ports matter: a memory array with no reset, a model; its size")


class Static(BaseModel):
    signal: str = Field(description="the signal, as a hierarchical name from the top (u_csr.reg_cfg_en, or a port name)")
    reason: str = Field(description="the evidence that it is written only while the design is idle / before enable and then held (spec section, RTL)")


class Constant(BaseModel):
    port: str = Field(description="the top's input that is tied in operation (a test or mode pin)")
    value: Literal["0", "1"]
    reason: str = Field(description="the evidence (spec section)")


class ResetSync(BaseModel):
    module: str = Field(description="the design's reset synchronizer module")
    depth: int = Field(2, description="its number of flops in series")
    reason: str = Field(description="the RTL that shows it is a reset synchronizer (file:line)")


class SanitySetup(BaseModel):
    resets: list[SetupReset] = Field(default_factory=list)
    blackbox: list[BlackBox] = Field(default_factory=list)
    quasi_static: list[Static] = Field(default_factory=list)
    constants: list[Constant] = Field(default_factory=list)
    reset_synchronizers: list[ResetSync] = Field(default_factory=list)
    summary: str = Field("", description="three or four sentences for the review: what was set and why, what was left out and why")


# -- facts ------------------------------------------------------------------------------------------------------------------------------------------

_ARRAY = re.compile(r"^\s*(?:logic|reg|bit)\b[^;=]*?\b(\w+)\s*\[([^\]]+)\]\s*(?:\[[^\]]+\]\s*)*;", re.M)


def arrays(rtl_files: list[Path]) -> dict[str, list[str]]:
    """module file → its unpacked arrays (`reg_mem [0:LPARA_ROWS-1]`): where the big memories are (the sizes as the RTL writes them)."""
    out: dict[str, list[str]] = {}
    for f in rtl_files:
        try:
            text = re.sub(r"//[^\n]*", "", f.read_text(errors="replace"))
        except OSError:
            continue
        found = [f"{m.group(1)} [{m.group(2).strip()}]" for m in _ARRAY.finditer(text)]
        if found:
            out[f.stem] = found[:6]
    return out


def design(filelist: Path, root: Path, top: str):
    """The design read with pyslang (q3tui.hdl.parse), or None when it cannot be elaborated here."""
    from q3tui.hdl.filelist import parse_filelist
    from q3tui.hdl.parse import parse_design

    try:
        return parse_design(parse_filelist(filelist, root), top)
    except Exception:  # noqa: BLE001
        return None


def top_ports(filelist: Path, root: Path, top: str, des=None) -> list[tuple[str, str]]:
    """(direction, name) of the top's ports; empty when the RTL cannot be elaborated here."""
    des = des if des is not None else design(filelist, root, top)
    info = des.modules.get(top) if des is not None else None
    return [(p.direction, p.name) for p in info.ports] if info else []


def blackbox_pins(des, top: str, modules: list[str]) -> list[dict]:
    """For each black-boxed module: its instances (paths from the top, `u_a/u_b`) and its data pins (not its clocks or resets): once a module is a
    black box the tool no longer knows which clock its pins belong to (VC Static: SETUP_BBOXPIN_UNCONSTRAINED) — they get an input / output delay."""
    if des is None:
        return []
    out = []
    for m in modules:
        info = des.modules.get(m)
        if info is None:
            continue
        paths: list[str] = []

        def walk(mod: str, prefix: str, depth: int = 0) -> None:
            node = des.modules.get(mod)
            if node is None or depth > 32:
                return
            for c in node.children:
                path = prefix + c["instance"]
                if c["module"] == m:
                    paths.append(path)
                else:
                    walk(c["module"], path + "/", depth + 1)

        walk(top, "")
        special = {c.name for c in info.clocks} | {r.name for r in info.resets}
        data = [p for p in info.ports if p.name not in special]
        out.append({"module": m, "instances": paths, "inputs": [p.name for p in data if p.direction == "input"],
                    "outputs": [p.name for p in data if p.direction == "output"]})
    return out


# -- checks -----------------------------------------------------------------------------------------------------------------------------------------

def problems(plan: SanitySetup, modules: set[str], ports: list[tuple[str, str]], clocks: list[str] | None = None) -> list[str]:
    """Names that are not in the design (code: the RTL's modules, the top's inputs). Quasi-static names are hierarchical: only a plain name (a port)
    is checked here; the dry run checks the rest."""
    inputs = {n for d, n in ports if d in ("input", "inout")}
    out = []
    for r in plan.resets:
        if inputs and r.port not in inputs:
            out.append(f"reset `{r.port}` is not an input of the top (inputs: {', '.join(sorted(inputs))})")
    for c in plan.constants:
        if inputs and c.port not in inputs:
            out.append(f"constant `{c.port}` is not an input of the top")
    for b in plan.blackbox:
        if b.module not in modules:
            out.append(f"black box `{b.module}` is not a module of the RTL")
        if b.clock and clocks is not None and b.clock not in clocks:
            out.append(f"black box `{b.module}`: clock `{b.clock}` is not an SDC clock ({', '.join(clocks) or 'none'})")
        if not b.clock and clocks is not None and len(clocks) > 1:
            out.append(f"black box `{b.module}`: name the clock its pins belong to (the SDC has {', '.join(clocks)})")
    for s in plan.reset_synchronizers:
        if s.module not in modules:
            out.append(f"reset synchronizer `{s.module}` is not a module of the RTL")
    for s in plan.quasi_static:
        if "." not in s.signal and "/" not in s.signal and inputs and s.signal not in {n for _, n in ports}:
            out.append(f"quasi-static `{s.signal}` is not a port of the top (give the hierarchical name of an internal signal: u_inst.signal)")
    return out


# -- the tool's commands ---------------------------------------------------------------------------------------------------------------------------

def blackbox_modules(plan: dict | None, options=None) -> list[str]:
    """The setup's black boxes and your option's (`options.blackbox` of the analysis step), in that order, once each."""
    mine = [b["module"] for b in (plan or {}).get("blackbox") or []]
    yours = re.split(r"[\s,]+", options) if isinstance(options, str) else [str(x) for x in options or []]
    return list(dict.fromkeys(m.strip() for m in [*mine, *yours] if m and m.strip()))


def tcl(plan: dict | None, role: str) -> str:
    """The setup's commands after the SDC (the resets are the script's own lines: `reset_lines`)."""
    if not plan:
        return ""
    out = []
    clocks = plan.get("clocks") or []
    by_mod = {b["module"]: b for b in plan.get("blackbox") or []}
    for b in plan.get("blackbox_pins") or []:  # (code computed the pins; the setup says the clock)
        clk = (by_mod.get(b["module"]) or {}).get("clock") or (clocks[0] if len(clocks) == 1 else "")
        if not clk:
            continue
        for kind, pins in (("set_output_delay", b.get("inputs") or []), ("set_input_delay", b.get("outputs") or [])):
            names = [f"{i}/{p}" for i in b.get("instances") or [] for p in pins]
            if names:
                out.append(f"{kind} -clock {{{clk}}} 0 [get_pins {{{' '.join(names)}}}]")
    for s in plan.get("quasi_static") or []:
        out.append(f"create_static -name {{{s['signal'].replace('.', '/')}}}")  # (a port, or a net / pin from the top: VC Static takes u_inst/sig, not u_inst.sig)
    for c in plan.get("constants") or []:
        out.append(f"set_case_analysis {c['value']} [get_ports {{{c['port']}}}]")
    if role == "rdc":
        for s in plan.get("reset_synchronizers") or []:
            d = max(1, int(s.get("depth") or 2))
            out.append(f"set_rdc_synchronizer -sync_cell {{{s['module']}}} -min_depth {d} -max_depth {d}")
    return "".join(f"{x}\n" for x in out)


def reset_lines(plan: dict | None) -> str | None:
    """`create_reset` for the setup's resets (None: the setup has none — the script's own reset lines stay)."""
    resets = (plan or {}).get("resets") or []
    if not resets:
        return None
    return "".join(f"create_reset -{r.get('kind') or 'async'} -sense {r['active']} {r['port']}\n" for r in resets)


def markdown(plan: dict) -> str:
    """The setup for reading (`reports/sanity_setup.md`, the review gate)."""
    rows = ["# CDC / RDC setup", "", plan.get("summary", ""), ""]

    def table(title: str, head: list[str], items: list[list[str]]) -> None:
        rows.extend([f"## {title}", ""])
        if not items:
            rows.extend(["(none)", ""])
            return
        rows.append("| " + " | ".join(head) + " |")
        rows.append("|" + "---|" * len(head))
        rows.extend("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", " ") for x in it) + " |" for it in items)
        rows.append("")

    table("Resets", ["Port", "Active", "Kind", "Why"], [[r["port"], r["active"], r.get("kind", "async"), r["reason"]] for r in plan.get("resets") or []])
    table("Black boxes", ["Module", "Clock of its pins", "Why"], [[b["module"], b.get("clock") or "(the only clock)", b["reason"]] for b in plan.get("blackbox") or []])
    table("Quasi-static signals", ["Signal", "Why"], [[s["signal"], s["reason"]] for s in plan.get("quasi_static") or []])
    table("Constants", ["Port", "Value", "Why"], [[c["port"], c["value"], c["reason"]] for c in plan.get("constants") or []])
    table("Reset synchronizers (RDC)", ["Module", "Depth", "Why"], [[s["module"], s.get("depth", 2), s["reason"]] for s in plan.get("reset_synchronizers") or []])
    return "\n".join(rows)


_TOOL_ERROR = re.compile(r"^(?:Error|\[Error\])|Error-\[|not found|cannot find|No such object|invalid", re.I)


def tool_errors(log: str) -> list[str]:
    """The setup's errors in a dry run's log (the tool's own messages about the commands; the vendor scripts' shell noise left out)."""
    return [x.strip() for x in log.splitlines() if _TOOL_ERROR.search(x) and "eval: line" not in x][:20]
