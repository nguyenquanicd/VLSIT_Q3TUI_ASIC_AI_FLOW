"""The library cells the netlist uses, read from the text Liberty (`.lib`) beside each `.db`: their pins and what each output computes.
The netlist-edit stages get it (no guess of a cell's function from its name) and `tcl.check_structure` checks a pin exists."""
from __future__ import annotations

import re
from pathlib import Path

_CELL = re.compile(r'^\s*cell\s*\(\s*"?([\w$]+)"?\s*\)', re.M)
_PIN = re.compile(r'(?<![\w])pin\s*\(\s*"?([\w$\[\]]+)"?\s*\)')  # (not pg_pin)
_DIR = re.compile(r'(?<![\w])direction\s*:\s*"?(\w+)"?')
_FUNC = re.compile(r'(?<![\w])function\s*:\s*"([^"]+)"')  # (not power_down_function)
_SEQ = re.compile(r'(?<![\w])(ff|latch)\s*\(([^)]*)\)\s*\{([^{}]*)\}')
_ATTR = re.compile(r'(\w+)\s*:\s*"([^"]+)"')
_index: dict[tuple[str, float], tuple[str, dict[str, tuple[int, int]]]] = {}


def text_lib(db: str | Path) -> Path | None:
    """The text Liberty of a `.db`: the same name with `.lib`, beside it; None when there is none."""
    p = Path(db).with_suffix(".lib")
    return p if p.is_file() else None


def _cells_of(lib: Path) -> tuple[str, dict[str, tuple[int, int]]]:
    """The file's text and where each cell's group is (cached per file and modification time: a std-cell .lib is ~100 MB)."""
    key = (str(lib), lib.stat().st_mtime)
    if key not in _index:
        text = lib.read_text(errors="replace")
        starts = [(m.group(1), m.start()) for m in _CELL.finditer(text)]
        spans = {name: (s, starts[i + 1][1] if i + 1 < len(starts) else len(text)) for i, (name, s) in enumerate(starts)}
        _index.clear()  # (one library at a time in memory)
        _index[key] = (text, spans)
    return _index[key]


def describe(block: str) -> dict:
    """{pins: {name: direction}, function: {output: expression}, seq: "ff: next_state D, clocked_on CP, …" or ""} of one cell group."""
    pins: dict[str, str] = {}
    function: dict[str, str] = {}
    marks = list(_PIN.finditer(block))
    for i, m in enumerate(marks):
        seg = block[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(block)]
        d = _DIR.search(seg)
        pins[m.group(1)] = d.group(1) if d else "?"
        f = _FUNC.search(seg)
        if f and pins[m.group(1)] == "output":
            function[m.group(1)] = f.group(1).strip()
    s = _SEQ.search(block)
    seq = f"{s.group(1)} ({s.group(2).strip()}): " + ", ".join(f"{k} {v}" for k, v in _ATTR.findall(s.group(3))) if s else ""
    return {"pins": pins, "function": function, "seq": seq}


def cells(libraries: list[str], names) -> dict[str, dict]:
    """{cell: describe(…)} for the cells named, from the text Liberty of each library (the first that has the cell); {} without one."""
    out: dict[str, dict] = {}
    want = set(names)
    for db in libraries:
        lib = text_lib(db)
        if lib is None or not want - set(out):
            continue
        text, spans = _cells_of(lib)
        for name in want - set(out):
            if name in spans:
                out[name] = describe(text[slice(*spans[name])])
    return out


def line(name: str, info: dict) -> str:
    """One cell for a prompt: `INR2D1 (in A1 B1): ZN = (!((!A1)+B1))`."""
    ins = " ".join(p for p, d in info["pins"].items() if d == "input")
    outs = "; ".join(f"{p} = {f}" for p, f in info["function"].items()) or "; ".join(p for p, d in info["pins"].items() if d == "output")
    return f"{name} (in {ins}): {outs}" + (f" — {info['seq']}" if info["seq"] else "")
