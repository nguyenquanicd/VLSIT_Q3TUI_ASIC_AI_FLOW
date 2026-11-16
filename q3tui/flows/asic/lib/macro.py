"""ASIC memory macros (the code of `asic_macro`): the memory wrappers of the RTL, the memory sources of the PDK, the choice, the ASIC body
of a wrapper, the Library Compiler script and the lock-step check of the ASIC body against the behavioural one.

- Wrappers: the modules named like the rule file's memory wrappers (`*_sram` / `*_rf` / `*_rom`, `port._WRAPPER`); their port widths come
  from the elaborated design (pyslang), what each port does from a small LLM stage (`MemSpec`, checked here against the widths).
- Sources: a memory compiler (an executable under a `Compiler/` folder of the PDK: found here, judged by an LLM stage that reads its kit,
  run only as the tool role `mem_compile` of config/tools.json) or the pre-generated macros — every Liberty file under a memory folder of
  the PDK with a `memory ()` group (cell, words, bits, area; the `minimum_period` of the clock pin; the Verilog model of the corner).
- Choice (code): the smallest total area of rows × columns of one macro that has the wrapper's ports, its write mask and a clock period at
  most the SDC's; the pins of a macro family (which pin is the clock, the chip enable, …, what the test pins are tied to) come from an LLM
  stage (`PinMap`), checked here against the Liberty pins.
- The ASIC body (code): the wrapper's own header, then the macros, the row decode, the write-mask expansion and the read mux on the
  registered row. It replaces the behavioural file in the synthesis and the equivalence check; `src/rtl/` is not touched."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from q3tui.flows.asic.lib.port import _WRAPPER

MACRO_JSON = "asic_macro.json"  # schemas/: per wrapper what implements it (macro, rows × columns, files, check)
MEM_PATH = re.compile(r"(?i)(sram|ram|rf|rom|mem)")  # shortcut: a macro must sit under a folder named like a memory; set pdk_root deeper if not
CORNER = re.compile(r"(?i)((?:tt|ssg|ffg|ss|ff|sf|fs)\d+p\d+v(?:\d+p\d+v)?m?\d+c)$")
DFT_PATH = re.compile(r"(?i)(mentor_dft|atpg|mbist|fscan|logicv|_pwr$)")
VERSION = 2  # of the choice rules: a new version chooses every wrapper again (2: fill ties such as {64{1'b1}} / '1)
REVIEW_BYTES = 4096  # a memory this size or more that ends up as flip-flops is reviewed by an LLM stage and asked about
CANDIDATES = 12  # the smallest tilings looked at per wrapper (each one's Liberty is read in full, its pin family may need an LLM stage)


# -- the LLM answers ------------------------------------------------------------------------------------------------------------

class WPort(BaseModel):
    kind: Literal["rw", "r", "w"] = Field(description="rw: one address for read and write; r: read only; w: write only")
    clk: str = Field(description="the clock port of the wrapper")
    addr: str = Field(description="the address port")
    din: str = Field("", description="the write data port (rw / w)")
    dout: str = Field("", description="the read data port (rw / r)")
    en: str = Field("", description="the port that enables an access (chip / read enable); empty: always enabled")
    en_low: bool = Field(False, description="en is active low")
    we: str = Field("", description="the write enable (rw: write when set, read otherwise; w: write when set); empty for r")
    we_low: bool = Field(False, description="we is active low")
    be: str = Field("", description="the byte / bit write enables; empty: whole words only")
    be_low: bool = Field(False, description="be is active low")


class MemSpec(BaseModel):
    words: int = Field(description="the number of words the storage holds (the array's depth as instantiated)")
    bits: int = Field(description="the word width")
    ports: list[WPort] = Field(description="the access ports of the wrapper, one per independent address")
    read_latency: int = Field(1, description="cycles from the address to the read data (1: registered read)")
    rom: bool = Field(False, description="a ROM (contents from a file, never written)")
    notes: str = Field("", description="read-during-write behaviour and anything else the ASIC body must keep, in one sentence")


class MPort(BaseModel):
    kind: Literal["rw", "r", "w"] = Field(description="rw: one address for read and write; r: read only; w: write only")
    clk: str = Field(description="the clock pin")
    addr: str = Field(description="the address bus")
    din: str = Field("", description="the data-in bus (rw / w)")
    dout: str = Field("", description="the data-out bus (rw / r)")
    en: str = Field("", description="the chip / port enable pin (CEB, REB, …); empty: none")
    en_low: bool = Field(True, description="en is active low")
    we: str = Field("", description="the write enable pin (WEB); empty: none (a w port then writes when en)")
    we_low: bool = Field(True, description="we is active low")
    bwe: str = Field("", description="the bit write enable bus (BWEB); empty: whole words only")
    bwe_low: bool = Field(True, description="bwe is active low")


class PinMap(BaseModel):
    ports: list[MPort] = Field(description="the functional ports of the macro")
    ties: dict[str, str] = Field(default_factory=dict, description="every other input pin (test, BIST, sleep, shut-down, margin, redundancy) "
                                                                  "and the constant it is tied to in normal operation, as Verilog: \"1'b0\" / \"1'b1\" sets every bit of the pin (any width), "
                                                                  "a sized constant (\"3'b010\") a field of exactly that width")
    notes: str = Field("", description="one sentence on the pins")


class Verdict(BaseModel):
    wrapper: str = Field(description="the wrapper module, as given")
    kind: Literal["check_wrong", "mismatch", "intended"] = Field(
        description="check_wrong: a code check rejected a macro that is right (the reason it gives is false); mismatch: a real reason no "
                    "macro fits that a change of the design would remove; intended: flip-flops are the right result")
    macro: str = Field("", description="check_wrong: the macro (cell name, as in the notes) that should be used")
    explanation: str = Field(description="one or two sentences for the designer: what was rejected and why that is right or wrong")
    request: str = Field("", description="mismatch: the change of the wrapper or its parent that would let a macro fit, worded as a spec "
                                         "change request (function, ports, latency — no macro or cell name)")


class Review(BaseModel):
    verdicts: list[Verdict] = Field(description="one per wrapper given")


class CompilerPlan(BaseModel):
    usable: bool = Field(description="true only when the compiler and the data it needs for this technology are there and it can make this memory")
    reason: str = Field(description="why (what is there, what is missing)")
    cmd: str = Field("", description="the command for the tool role mem_compile, with {config} (the input file) and {workdir} (where it writes)")
    config: str = Field("", description="the compiler's input file for this memory (words, bits, mux, options; the clock target if it takes one)")
    lib_glob: str = Field("", description="where the .lib of the corner lands, a glob relative to {workdir}")
    v_glob: str = Field("", description="where the Verilog model lands, a glob relative to {workdir}")
    lef_glob: str = Field("", description="where the LEF lands, a glob relative to {workdir}")


# -- the wrappers ------------------------------------------------------------------------------------------------------------

def wrappers(files: list[Path]) -> dict[str, Path]:
    """{module: file} of the memory wrappers of the RTL."""
    out = {}
    for f in files:
        for m in re.finditer(r"(?m)^\s*module\s+(\w+)", f.read_text(errors="replace")):
            if _WRAPPER.search(m.group(1)):
                out[m.group(1)] = f
    return out


def width(type_text: str) -> int:
    """The width of an elaborated port type (`logic[127:0]` → 128, `logic` → 1)."""
    m = re.search(r"\[(\d+):(\d+)\]", type_text)
    return abs(int(m.group(1)) - int(m.group(2))) + 1 if m else 1


def spec_problems(spec: MemSpec, ports: dict[str, tuple[str, int]]) -> list[str]:
    """What is wrong in a MemSpec against the wrapper's ports {name: (direction, width)}."""
    bad = []
    if spec.read_latency != 1:
        bad.append(f"read latency {spec.read_latency}: only registered reads (1) are made from macros")
    for i, p in enumerate(spec.ports):
        need = {"clk": p.clk, "addr": p.addr, **({"din": p.din} if p.kind != "r" else {}), **({"dout": p.dout} if p.kind != "w" else {})}
        for role, name in {**need, "en": p.en, "we": p.we, "be": p.be}.items():
            if role in need and not name:
                bad.append(f"port {i} ({p.kind}): no {role}")
            elif name and name not in ports:
                bad.append(f"port {i}: `{name}` is not a port of the wrapper")
        if p.addr in ports and 2 ** ports[p.addr][1] < spec.words:
            bad.append(f"{spec.words} words do not fit the {ports[p.addr][1]}-bit address `{p.addr}`")
        for name in (p.din, p.dout):
            if name in ports and ports[name][1] != spec.bits:
                bad.append(f"`{name}` is {ports[name][1]} bits, not {spec.bits}")
        if p.be in ports and spec.bits % ports[p.be][1]:
            bad.append(f"`{p.be}` ({ports[p.be][1]} bits) does not divide the {spec.bits}-bit word")
        if p.kind == "rw" and not p.we:
            bad.append(f"port {i} (rw): no write enable")
    return bad


# -- the PDK ------------------------------------------------------------------------------------------------------------------

def pdk_root(library: str) -> Path | None:
    """The PDK folder of a standard-cell library: the nearest parent that has a memory folder (MEMORY / SRAM / …)."""
    for parent in list(Path(library).parents)[:-1]:  # (every parent but `/`: a vendor kit nests its .db 10+ folders deep)
        try:
            if any(c.is_dir() and re.fullmatch(r"(?i)memory|sram|mem|memories", c.name) for c in parent.iterdir()):
                return parent
        except OSError:
            continue
    return None


def corner_of(path: str) -> str:
    """The corner a library file is for (`…tt0p9v25c.db` → tt0p9v25c), or ''."""
    m = CORNER.search(Path(path).stem.split("_")[-1]) or CORNER.search(Path(path).stem)
    return m.group(1).lower() if m else ""


@dataclass
class Macro:
    name: str  # the cell (= the Verilog module)
    lib: str  # the Liberty file of the corner
    corner: str
    words: int
    bits: int
    addr_bits: int
    area: float
    model: str = ""  # the Verilog model of the corner
    lef: str = ""
    library: str = ""  # the Liberty library name (write_lib needs it)
    kind: str = "ram"


def _head(path: Path, n: int = 262144) -> str:
    try:
        with open(path, errors="replace") as fh:
            return fh.read(n)
    except OSError:
        return ""


def lib_header(text: str) -> dict | None:
    """{library, cell, kind, addr_bits, bits, area} of a memory Liberty file; None for any other library."""
    mem = re.search(r"memory\s*\(\s*\)\s*\{([^}]*)\}", text)
    cell = re.search(r"\bcell\s*\(\s*\"?(\w+)\"?\s*\)", text)
    if not mem or not cell:
        return None
    aw, ww = re.search(r"address_width\s*:\s*(\d+)", mem.group(1)), re.search(r"word_width\s*:\s*(\d+)", mem.group(1))
    if not aw or not ww:
        return None
    kind = re.search(r"type\s*:\s*(\w+)", mem.group(1))
    area = re.search(r"\barea\s*:\s*([\d.]+)", text[cell.end():])
    lib = re.search(r"library\s*\(\s*\"?([\w.]+)\"?\s*\)", text)
    return {"library": lib.group(1) if lib else cell.group(1), "cell": cell.group(1), "kind": kind.group(1).lower() if kind else "ram",
            "addr_bits": int(aw.group(1)), "bits": int(ww.group(1)), "area": float(area.group(1)) if area else 0.0}


def lib_pins(text: str) -> dict[str, tuple[str, int]]:
    """{pin: (direction, width)} of a cell's Liberty text (buses by their bus_type's bit_width)."""
    types = {n: int(w) for n, w in re.findall(r"\btype\s*\(\s*\"?(\w+)\"?\s*\)\s*\{[^}]*?bit_width\s*:\s*(\d+)", text)}
    out = {}
    for m in re.finditer(r"\b(bus|pin)\s*\(\s*\"?([\w\[\]:]+)\"?\s*\)\s*\{", text):
        name = m.group(2)
        if "[" in name or name in out:
            continue
        seg = text[m.end():m.end() + 4000]
        d = re.search(r"direction\s*:\s*\"?(\w+)", seg)
        w = 1
        if m.group(1) == "bus":
            bt = re.search(r"bus_type\s*:\s*\"?(\w+)", seg)
            w = types.get(bt.group(1), 1) if bt else 1
        out[name] = (d.group(1) if d else "", w)
    return out


def min_period_ns(text: str, clk: str) -> float | None:
    """The worst `minimum_period` of the clock pin (the table's largest value), in ns."""
    m = re.search(rf"\bpin\s*\(\s*\"?{re.escape(clk)}\"?\s*\)\s*\{{", text)
    if not m:
        return None
    nxt = re.search(r"\b(?:pin|bus)\s*\(", text[m.end():])
    seg = text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]
    vals = [float(v) for t in re.finditer(r"timing_type\s*:\s*\"?minimum_period\"?(.*?)\}\s*\}", seg, re.S)
            for v in re.findall(r"[\d.]+(?:e-?\d+)?", " ".join(re.findall(r"values\s*\(([^)]*)\)", t.group(1))))]
    if not vals:
        return None
    unit = re.search(r"time_unit\s*:\s*\"?1(ps|ns)", text)
    return max(vals) / (1000.0 if unit and unit.group(1) == "ps" else 1.0)


def _words(name: str, addr_bits: int) -> int:
    m = re.search(r"(?i)(\d+)x(\d+)", name)
    return int(m.group(1)) if m else 2 ** addr_bits


def scan(root: Path, corner: str) -> list[Macro]:
    """The pre-generated macros under `root`, one Liberty file each: the corner's when there is one (else a file of the same process
    letters, else any). Only files under a memory-named folder, and only Liberty files with a `memory ()` group, count."""
    libs: dict[str, dict[str, Path]] = {}  # macro stem (without the corner) -> {corner: file}
    views: dict[str, Path] = {}  # file stem -> .v / .lef
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if not MEM_PATH.search(dirpath[len(str(root)):]) or DFT_PATH.search(dirpath):
            continue
        for f in files:
            p = Path(dirpath) / f
            if f.endswith(".lib") and not DFT_PATH.search(p.stem):
                c = corner_of(f)
                base = p.stem[: -len(c) - 1] if c and p.stem.lower().endswith("_" + c) else p.stem
                libs.setdefault(base, {})[c] = p
            elif f.endswith((".v", ".lef")) and not DFT_PATH.search(p.stem):
                views.setdefault(f, p)
    out: dict[str, Macro] = {}
    want = corner.lower()
    for base, by in sorted(libs.items()):
        pick = by.get(want) or next((p for c, p in sorted(by.items()) if want and c[:2] == want[:2]), None) or by[sorted(by)[0]]
        h = lib_header(_head(pick))
        if h is None:
            continue
        c = next(k for k, v in by.items() if v == pick)
        model = views.get(f"{base}_{c}.v") or views.get(f"{h['cell']}_{c}.v") or views.get(f"{h['cell']}.v") or views.get(f"{base}.v")
        lef = views.get(f"{h['cell']}.lef") or views.get(f"{base}.lef")
        m = Macro(h["cell"], str(pick), c, _words(h["cell"], h["addr_bits"]), h["bits"], h["addr_bits"], h["area"],
                  str(model) if model else "", str(lef) if lef else "", h["library"], h["kind"])
        seen = out.get(m.name)
        if seen is None or (seen.corner != want and m.corner == want):  # (one cell in several view folders: the corner's file wins)
            out[m.name] = m
    return list(out.values())


def compilers(root: Path, limit: int = 20) -> list[str]:
    """Executables of memory compilers under `root` (under a `Compiler` folder, or named like one): candidates for the LLM to judge."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if not MEM_PATH.search(dirpath[len(str(root)):]):
            continue
        for f in files:
            p = Path(dirpath) / f
            if (re.search(r"(?i)/compiler/", str(p)) or re.search(r"(?i)^(mc2|.*compiler|sram_sp\w*|sram_dp\w*|rf_sp\w*|rf_2p\w*)$", f)) \
                    and os.access(p, os.X_OK) and p.is_file() and not re.search(r"(?i)(\.(so|pdf|txt|html?|so\.\d+)$|^readme|^license)", f):
                out.append(str(p))
                if len(out) >= limit:
                    return out
    return out


def catalog_key(root: Path, corner: str) -> str:
    try:
        stamp = max(os.stat(root).st_mtime, *(os.stat(p).st_mtime for p in root.iterdir() if p.is_dir()))
    except (OSError, ValueError):
        stamp = 0
    return f"{root}|{corner}|{stamp}"  # shortcut: a change deep in the tree is not seen; reset the step to rescan


def load_catalog(path: Path, key: str) -> list[Macro] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return [Macro(**m) for m in data["macros"]] if data.get("key") == key else None


def save_catalog(path: Path, key: str, macros: list[Macro]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"key": key, "macros": [asdict(m) for m in macros]}))


# -- the choice ---------------------------------------------------------------------------------------------------------------

@dataclass
class Tiling:
    macro: Macro
    rows: int
    cols: int

    @property
    def count(self) -> int:
        return self.rows * self.cols

    @property
    def area(self) -> float:
        return self.count * self.macro.area


def tilings(spec: MemSpec, macros: list[Macro]) -> list[Tiling]:
    """Every macro as rows × columns for the wrapper's words × bits, smallest total area first (then fewer macros). A macro whose words
    are not a power of two can only be one row (its rows would need a divider)."""
    out = []
    for m in macros:
        if m.words <= 0 or m.bits <= 0 or (spec.rom and m.kind != "rom") or (not spec.rom and m.kind == "rom"):
            continue
        rows, cols = math.ceil(spec.words / m.words), math.ceil(spec.bits / m.bits)
        if rows > 1 and m.words != 2 ** m.addr_bits:
            continue
        if rows * cols > 256:  # (a tiling this size is a sign the macro is the wrong one)
            continue
        out.append(Tiling(m, rows, cols))
    return sorted(out, key=lambda t: (t.area, t.count, t.macro.name))


_FILL = re.compile(r"'([01])|1'[bB]([01])|\{\d+\{1'[bB]([01])\}\}|(\d+)'[bB]([01])\5*")


def fill_bit(value: str) -> str | None:
    """'0' / '1' when a tie sets every bit of its pin to that bit (`1'b1`, `'1`, `{64{1'b1}}`, `4'b1111`), else None."""
    m = _FILL.fullmatch(value.replace(" ", "").replace("_", ""))
    if m is None:
        return None
    if m.group(4):  # (a sized all-0 / all-1 constant: only when every bit is the same)
        bits = value.replace(" ", "").replace("_", "").split("'")[1][1:]
        return bits[0] if set(bits) <= {bits[0]} and len(bits) == int(m.group(4)) else None
    return next(g for g in m.groups()[:3] if g)


def tie_expr(value: str) -> str:
    """A tie as it goes on the pin: a fill as `'0` / `'1` (the pin's width, for every macro of the family), a field as given."""
    b = fill_bit(value)
    return f"'{b}" if b is not None else value.strip()


def pin_key(pins: dict[str, tuple[str, int]]) -> str:
    """The pins of a macro without their widths: macros of one family share it (and one PinMap)."""
    return ",".join(f"{n}:{d}" for n, (d, _w) in sorted(pins.items()))


def pinmap_problems(pm: PinMap, pins: dict[str, tuple[str, int]], m: Macro) -> list[str]:
    """What is wrong in a PinMap against the Liberty pins of the macro."""
    bad, used = [], set()
    for i, p in enumerate(pm.ports):
        roles = {"clk": (p.clk, "input", 1), "addr": (p.addr, "input", m.addr_bits), "din": (p.din, "input", m.bits), "dout": (p.dout, "output", m.bits),
                 "en": (p.en, "input", 1), "we": (p.we, "input", 1), "bwe": (p.bwe, "input", m.bits)}
        for role, (name, direction, w) in roles.items():
            if not name:
                if role in ("clk", "addr") or (role == "din" and p.kind != "r") or (role == "dout" and p.kind != "w"):
                    bad.append(f"port {i} ({p.kind}): no {role}")
                continue
            if name not in pins:
                bad.append(f"port {i}: `{name}` is not a pin of {m.name}")
                continue
            if pins[name][0] != direction or pins[name][1] != w:
                bad.append(f"port {i}: `{name}` is {pins[name][0]} [{pins[name][1]}], not {direction} [{w}] for {role}")
            used.add(name)
    for name, value in pm.ties.items():
        if name not in pins or pins[name][0] != "input":
            bad.append(f"tie `{name}`: not an input pin of {m.name}")
        elif fill_bit(value) is None and not re.fullmatch(r"\d+'[bhd][0-9a-fA-F_]+", value.replace(" ", "")):
            bad.append(f"tie `{name}` = `{value}`: not a Verilog constant")
        elif fill_bit(value) is None and int(value.split("'")[0]) != pins[name][1]:
            bad.append(f"tie `{name}` = `{value}`: {pins[name][1]} bits wide, not {value.split(chr(39))[0]}")
        used.add(name)
    left = sorted(n for n, (d, _w) in pins.items() if d == "input" and n not in used)
    if left:
        bad.append(f"input pin(s) neither mapped nor tied: {', '.join(left)}")
    return bad


def fits(spec: MemSpec, pm: PinMap) -> str:
    """'' when the macro's ports can carry the wrapper's (the same kinds, a bit mask where the wrapper writes bytes), else why not."""
    if sorted(p.kind for p in spec.ports) != sorted(p.kind for p in pm.ports):
        return f"ports {'/'.join(sorted(p.kind for p in pm.ports))}, the wrapper needs {'/'.join(sorted(p.kind for p in spec.ports))}"
    for wp in spec.ports:
        mp = next(p for p in pm.ports if p.kind == wp.kind)
        if wp.be and not mp.bwe:
            return "no bit write enable for the wrapper's byte enables"
    return ""


# -- the ASIC body ------------------------------------------------------------------------------------------------------------

def _header(text: str, module: str) -> tuple[str, str, str]:
    """(what comes before the module — `timescale, imports, other modules of the file —, the module's header up to the `;` after its
    port list, what comes after its `endmodule`)."""
    m = re.search(rf"(?m)^\s*module\s+{re.escape(module)}\b", text)
    if not m:
        raise ValueError(f"module {module} not found")
    i, depth = m.end(), 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth == 0:  # shortcut: a `;` or unbalanced paren inside a header comment breaks this; the check catches it
            end = re.search(r"\bendmodule\b[^\n]*\n?", text[i:])
            return text[: m.start()], text[m.start(): i + 1], (text[i + end.end():] if end else "")
        i += 1
    raise ValueError(f"the header of {module} has no end")


def _pol(expr: str, low: bool) -> str:
    return f"~({expr})" if low else expr


def render(module: str, behavioural: str, spec: MemSpec, t: Tiling, pm: PinMap, ports: dict[str, tuple[str, int]], name: str | None = None) -> str:
    """The ASIC body of a wrapper: its own header (parameters, ports: unchanged), `rows × cols` macros, the row decode, the write mask,
    the read mux on the registered row (read latency 1). `name`: another module name (the lock-step check has both bodies)."""
    pre, head, post = _header(behavioural, module)
    if name:  # (the check's copy: this module alone — the file's other modules are in the behavioural file it is compared with)
        head = re.sub(rf"\bmodule\s+{re.escape(module)}\b", f"module {name}", head, count=1)
        pre, post = ("" if re.search(r"(?m)^\s*module\b", pre) else pre), ""
    m, rows, cols = t.macro, t.rows, t.cols
    rb, full = max(1, math.ceil(math.log2(rows))) if rows > 1 else 0, cols * m.bits
    lines = [f"  // generated by Q3TUI (asic_macro): {rows} x {cols} {m.name} ({m.words} x {m.bits}, {m.corner}) for {spec.words} x {spec.bits}"]
    by_kind: dict[str, list[MPort]] = {}
    for p in pm.ports:
        by_kind.setdefault(p.kind, []).append(p)
    pairs = [(wp, by_kind[wp.kind].pop(0)) for wp in spec.ports]
    conns: dict[tuple[int, int], list[str]] = {(r, c): [] for r in range(rows) for c in range(cols)}
    for k, (wp, mp) in enumerate(pairs):
        aw = ports[wp.addr][1]
        en = _pol(wp.en, wp.en_low) if wp.en else "1'b1"
        we = _pol(wp.we, wp.we_low) if wp.we else ("1'b1" if wp.kind == "w" else "1'b0")
        act = {"rw": en, "r": en, "w": f"({en}) & ({we})"}[wp.kind]
        lines.append(f"  logic q3_act{k};\n  assign q3_act{k} = {act};")
        lo = f"{wp.addr}[{min(aw, m.addr_bits) - 1}:0]"
        lines.append(f"  logic [{m.addr_bits - 1}:0] q3_addr{k};\n  assign q3_addr{k} = " + (f"{{{m.addr_bits - aw}'b0, {lo}}};" if aw < m.addr_bits else f"{lo};"))
        if rows > 1:
            lines.append(f"  logic [{rb - 1}:0] q3_row{k};\n  assign q3_row{k} = {wp.addr}[{m.addr_bits + rb - 1}:{m.addr_bits}];")
        if wp.kind != "r":
            pad = full - spec.bits
            lines.append(f"  logic [{full - 1}:0] q3_din{k};\n  assign q3_din{k} = " + (f"{{{pad}'b0, {wp.din}}};" if pad else f"{wp.din};"))
            if mp.bwe:
                if wp.be:
                    g = spec.bits // ports[wp.be][1]
                    lines.append(f"  logic [{ports[wp.be][1] - 1}:0] q3_be{k};\n  assign q3_be{k} = {_pol(wp.be, wp.be_low)};")
                    lines.append(f"  logic [{spec.bits - 1}:0] q3_mask{k};\n  always_comb for (int i = 0; i < {spec.bits}; i++) q3_mask{k}[i] = q3_be{k}[i / {g}];")
                    mask = f"q3_mask{k}"
                else:
                    mask = f"{{{spec.bits}{{1'b1}}}}"
                lines.append(f"  logic [{full - 1}:0] q3_bwe{k};\n  assign q3_bwe{k} = " + (f"{{{full - spec.bits}'b0, {mask}}};" if full > spec.bits else f"{mask};"))
        if wp.kind != "w":
            for r in range(rows):
                lines.append(f"  logic [{full - 1}:0] q3_rd{k}_r{r};")
            if rows > 1:
                lines.append(f"  logic [{rb - 1}:0] q3_row{k}_q;\n  always_ff @(posedge {wp.clk}) if (q3_act{k}) q3_row{k}_q <= q3_row{k};")
                lines.append(f"  always_comb begin\n    {wp.dout} = q3_rd{k}_r0[{spec.bits - 1}:0];\n    case (q3_row{k}_q)")
                lines += [f"      {rb}'d{r}: {wp.dout} = q3_rd{k}_r{r}[{spec.bits - 1}:0];" for r in range(1, rows)]
                lines.append("      default: ;\n    endcase\n  end")
            else:
                lines.append(f"  assign {wp.dout} = q3_rd{k}_r0[{spec.bits - 1}:0];")
        for r in range(rows):
            sel = f"q3_act{k} & (q3_row{k} == {rb}'d{r})" if rows > 1 else f"q3_act{k}"
            for c in range(cols):
                lo_b, hi_b = c * m.bits, (c + 1) * m.bits - 1
                cc = conns[(r, c)]
                cc.append(f".{mp.clk}({wp.clk})")
                cc.append(f".{mp.addr}(q3_addr{k})")
                if mp.en:
                    cc.append(f".{mp.en}({_pol(sel, mp.en_low)})")
                if mp.we:
                    w_expr = f"({sel}) & ({we})" if wp.kind == "rw" else sel
                    cc.append(f".{mp.we}({_pol(w_expr, mp.we_low)})")
                elif wp.kind == "rw":
                    raise ValueError(f"{m.name}: an rw port without a write enable pin")
                if wp.kind != "r":
                    cc.append(f".{mp.din}(q3_din{k}[{hi_b}:{lo_b}])")
                    if mp.bwe:
                        cc.append(f".{mp.bwe}({_pol(f'q3_bwe{k}[{hi_b}:{lo_b}]', mp.bwe_low)})")
                if wp.kind != "w":
                    cc.append(f".{mp.dout}(q3_rd{k}_r{r}[{hi_b}:{lo_b}])")
    for (r, c), cc in conns.items():
        cc += [f".{pin}({tie_expr(value)})" for pin, value in pm.ties.items()]
        lines.append(f"  {m.name} u_mem_r{r}_c{c} (\n    " + ",\n    ".join(cc) + "\n  );")
    return pre + head + "\n" + "\n".join(lines) + "\nendmodule\n" + post


# -- tools --------------------------------------------------------------------------------------------------------------------

def lc_script(items: list[tuple[str, str, Path]]) -> str:
    """The Library Compiler script: each (library name, .lib, .db) read and written as a .db."""
    lines = ["# generated by Q3TUI (asic_macro): the macros' Liberty files as .db for Design Compiler / Formality"]
    for library, lib, db in items:
        lines += [f'read_lib "{lib}"', f'write_lib {library} -format db -output "{db}"', f"remove_lib {library}"]
    return "\n".join(lines + ["exit"]) + "\n"


def check_tb(module: str, asic: str, spec: MemSpec, ports: dict[str, tuple[str, int]], n_addr: int = 16, n_ops: int = 400) -> str:
    """The lock-step check: the behavioural wrapper and its ASIC body (module `asic`) side by side, every input driven alike; first every
    test address is written in full, then random reads and writes (random masks); after each read both read data must be equal.
    Prints `Q3TUI_MEMCHECK: PASS|FAIL <errors>`."""
    clks = {p.clk for p in spec.ports}
    decl = [f"  logic {'[' + str(w - 1) + ':0] ' if w > 1 else ''}{n};" for n, (d, w) in ports.items() if d == "input"]
    outs = [(n, w) for n, (d, w) in ports.items() if d == "output"]
    decl += [f"  logic {'[' + str(w - 1) + ':0] ' if w > 1 else ''}{n}_ref, {n}_dut;" for n, w in outs]
    conn = lambda suf: ", ".join([f".{n}({n})" for n, (d, _w) in ports.items() if d == "input"] + [f".{n}({n}{suf})" for n, _w in outs])  # noqa: E731
    step = max(1, spec.words // n_addr)
    body = [f"  int errors = 0;\n  int unsigned addrs[{n_addr}];",
            "  always #5 begin " + " ".join(f"{c} = ~{c};" for c in clks) + " end"]
    idle, drive_rd, drive_wr = [], [], []
    for k, p in enumerate(spec.ports):
        if p.en:
            idle.append(f"{p.en} = {int(p.en_low)};")
        if p.we:
            idle.append(f"{p.we} = {int(p.we_low)};")
        if p.kind != "w":
            rd = [f"{p.addr} = a;"] + ([f"{p.en} = {int(not p.en_low)};"] if p.en else []) + ([f"{p.we} = {int(p.we_low)};"] if p.we else [])
            drive_rd.append((k, rd, p.dout))
        if p.kind != "r":
            wr = [f"{p.addr} = a;", f"{p.din} = {{{max(1, math.ceil(spec.bits / 32))}{{$urandom}}}};"] + ([f"{p.en} = {int(not p.en_low)};"] if p.en else []) \
                + ([f"{p.we} = {int(not p.we_low)};"] if p.we else [])
            if p.be:
                wr.append(f"{p.be} = full ? {{{ports[p.be][1]}{{1'b{int(not p.be_low)}}}}} : {{{max(1, math.ceil(ports[p.be][1] / 32))}{{$urandom}}}};")
            drive_wr.append((k, wr))
    body.append("  task automatic idle();\n    " + " ".join(idle or ["/* nothing */"]) + "\n  endtask")
    for k, wr in drive_wr:
        body.append(f"  task automatic write{k}(int unsigned a, bit full);\n    " + "\n    ".join(wr) + f"\n    @(posedge {spec.ports[k].clk}); #1 idle();\n  endtask")
    for k, rd, dout in drive_rd:
        body.append(f"  task automatic read{k}(int unsigned a);\n    " + "\n    ".join(rd) + f"\n    @(posedge {spec.ports[k].clk}); #1 idle();\n"
                    f"    if ({dout}_ref !== {dout}_dut) begin errors++; if (errors < 10) $display(\"Q3TUI_MEMCHECK: mismatch at %0d: %h != %h\", a, {dout}_ref, {dout}_dut); end\n  endtask")
    wk, rk = (drive_wr[0][0] if drive_wr else None), (drive_rd[0][0] if drive_rd else None)
    init = [" ".join(f"{n} = '0;" for n, (d, _w) in ports.items() if d == "input" and n not in clks), "idle();",
            f"for (int i = 0; i < {n_addr}; i++) addrs[i] = (i * {step} + $urandom_range({step - 1}, 0)) % {spec.words};",
            "repeat (2) @(posedge " + next(iter(clks)) + "); #1;"]
    if wk is not None:
        init.append(f"for (int i = 0; i < {n_addr}; i++) write{wk}(addrs[i], 1);")
    loop = []
    if rk is not None and wk is not None:
        loop = [f"repeat ({n_ops}) begin", f"  if ($urandom_range(1, 0)) write{wk}(addrs[$urandom_range({n_addr - 1}, 0)], 0);",
                f"  else read{rk}(addrs[$urandom_range({n_addr - 1}, 0)]);", "end",
                f"for (int i = 0; i < {n_addr}; i++) read{rk}(addrs[i]);"]
    elif rk is not None:
        loop = [f"for (int i = 0; i < {n_addr}; i++) read{rk}(addrs[i]);"]
    body.append("  initial begin\n    " + " ".join(f"{c} = 0;" for c in clks) + "\n    " + "\n    ".join(init + loop)
                + "\n    $display(\"Q3TUI_MEMCHECK: %s %0d\", errors ? \"FAIL\" : \"PASS\", errors);\n    $finish;\n  end")
    return (f"// generated by Q3TUI (asic_macro): {module} (behavioural) against {asic} (macros), in lock-step (the time scale: the simulator's)\nmodule q3_memcheck;\n"
            + "\n".join(decl) + f"\n  {module} u_ref ({conn('_ref')});\n  {asic} u_dut ({conn('_dut')});\n" + "\n".join(body) + "\nendmodule\n")


def check_result(log: str) -> dict:
    m = re.search(r"Q3TUI_MEMCHECK: (PASS|FAIL) (\d+)", log)
    return {"status": m.group(1).lower(), "errors": int(m.group(2))} if m else {"status": "unknown"}


# -- what the synthesis takes -------------------------------------------------------------------------------------------------

def swapped(rtl_files: list[Path], data: dict, root: Path) -> list[Path]:
    """The RTL files with each implemented wrapper's file replaced by its ASIC body (which keeps the file's other modules; shortcut: two
    wrappers in one file — the second body keeps the first behavioural; give each wrapper its own file)."""
    impl = {w["file"]: root / w["asic_file"] for w in (data or {}).get("wrappers", {}).values() if w.get("asic_file") and (root / w["asic_file"]).is_file()}
    out = []
    for f in rtl_files:
        rel = str(f.relative_to(root)) if f.is_relative_to(root) else str(f)
        out.append(impl.get(rel, f))
    return out


def macro_dbs(data: dict, root: Path) -> list[str]:
    """The .db files of the macros the wrappers use (for link_library / Formality's read_db)."""
    dbs = [str(root / w["db"]) for w in (data or {}).get("wrappers", {}).values() if w.get("db") and w.get("asic_file")]
    return list(dict.fromkeys(dbs))


def macro_cells(data: dict) -> list[str]:
    return list(dict.fromkeys(w["macro"] for w in (data or {}).get("wrappers", {}).values() if w.get("asic_file") and w.get("macro")))


@dataclass
class Result:
    module: str
    file: str
    how: str  # macros | compiled | flops
    why: str = ""
    macro: str = ""
    rows: int = 0
    cols: int = 0
    area_um2: float = 0.0
    corner: str = ""
    asic_file: str = ""
    lib: str = ""
    library: str = ""  # the Liberty library name (write_lib)
    db: str = ""
    model: str = ""
    lef: str = ""
    check: dict = field(default_factory=dict)
    key: str = ""
    spec: dict = field(default_factory=dict)
