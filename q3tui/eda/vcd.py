"""Reading a VCD waveform (IEEE 1364 value change dump) by code: the signals it has, their values in a time window, when one takes a value.

Vendor-agnostic: a simulator dumps VCD itself, or its own format is converted (the `wave` tool role's command, e.g. VCS: VPD → `vpd2vcd`). Times are given and
returned in ns. A dump is read line by line (big dumps are not held in memory); the header is cached by file and mtime."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_UNITS = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3, "fs": 1e-6}


@dataclass
class Var:
    code: str  # the VCD identifier code
    name: str  # full hierarchical name: tb_top.u_dut.u_x.sig
    width: int
    kind: str = "wire"


@dataclass
class Header:
    vars: list[Var] = field(default_factory=list)
    ns_per_tick: float = 1.0
    end_tick: int = 0  # the last time in the dump

    def end_ns(self) -> float:
        return self.end_tick * self.ns_per_tick


_HEADERS: dict[tuple[str, float], Header] = {}


def _timescale(text: str) -> float:
    m = re.match(r"\s*(\d+)\s*([munpf]?s)", text)
    return int(m.group(1)) * _UNITS[m.group(2)] if m else 1.0


def header(path: Path) -> Header:
    """The signals of the dump and its time unit (and the dump's last time)."""
    key = (str(path), path.stat().st_mtime)
    if key in _HEADERS:
        return _HEADERS[key]
    h = Header()
    scope: list[str] = []
    pending = ""  # a $keyword … $end that spans several lines
    last = 0
    with path.open(errors="replace") as f:
        for line in f:
            if pending or line.lstrip().startswith("$"):
                pending += " " + line.strip()
                if "$end" not in pending:
                    continue
                words = pending.split()
                pending = ""
                if words[0] == "$scope":
                    scope.append(words[2])
                elif words[0] == "$upscope":
                    scope.pop() if scope else None
                elif words[0] == "$timescale":
                    h.ns_per_tick = _timescale(" ".join(words[1:-1]))
                elif words[0] == "$var" and len(words) >= 6:
                    h.vars.append(Var(words[3], ".".join([*scope, words[4]]), int(words[2]) if words[2].isdigit() else 1, words[1]))
                continue
            if line.startswith("#"):
                try:
                    last = int(line[1:])
                except ValueError:
                    pass
    h.end_tick = last
    _HEADERS[key] = h
    return h


def resolve(h: Header, name: str) -> list[Var]:
    """The signals a name means: the full name, else every signal whose name ends with it (`u_csr.o_illegal`)."""
    name = name.strip()
    exact = [v for v in h.vars if v.name == name]
    if exact:
        return exact[:1]
    tail = "." + name.lstrip(".")
    return [v for v in h.vars if v.name.endswith(tail)]


def find_vars(h: Header, pattern: str) -> list[Var]:
    """Signals whose name matches `pattern` (a regular expression, or a plain substring when it is not one)."""
    try:
        rx = re.compile(pattern, re.I)
        return [v for v in h.vars if rx.search(v.name)]
    except re.error:
        return [v for v in h.vars if pattern.lower() in v.name.lower()]


def show(value: str, width: int) -> str:
    """A value as the dump has it, vectors in hex when they have no x / z bit."""
    if width <= 1 or not value or value[0] in "rR":
        return value
    bits = value.lower()
    if set(bits) <= {"0", "1"}:
        digits = max(1, (width + 3) // 4)
        return f"'h{int(bits, 2):0{digits}x}"
    return f"'b{bits}"


def _normal(value: str) -> str | int:
    """What a user value means: 1, 0x1f, 'h1f, b101, 31 → an int; x / z words stay text."""
    v = value.strip().lower().replace("_", "")
    for prefix, base in (("0x", 16), ("'h", 16), ("h", 16), ("0b", 2), ("'b", 2), ("b", 2), ("'d", 10), ("d", 10)):
        if v.startswith(prefix) and v[len(prefix):]:
            try:
                return int(v[len(prefix):], base)
            except ValueError:
                return v
    try:
        return int(v)
    except ValueError:
        return v


def _as(value: str) -> str | int:
    bits = value.lower()
    if bits and set(bits) <= {"0", "1"}:
        return int(bits, 2)
    return bits


def _changes(path: Path, codes: set[str]):
    """(tick, code, value) for every change of the signals `codes`, in time order."""
    tick = 0
    in_header = True
    with path.open(errors="replace") as f:
        for line in f:
            if in_header:
                if "$enddefinitions" in line:
                    in_header = False
                continue
            line = line.strip()
            if not line or line.startswith("$"):
                continue
            c = line[0]
            if c == "#":
                try:
                    tick = int(line[1:])
                except ValueError:
                    pass
            elif c in "bBrR":
                value, _, code = line[1:].partition(" ")
                if code.strip() in codes:
                    yield tick, code.strip(), (value if c in "bB" else "r" + value)
            elif c in "01xXzZ":
                if line[1:] in codes:
                    yield tick, line[1:], c.lower()


def values(path: Path, names: list[str], start_ns: float = 0.0, end_ns: float | None = None, max_changes: int = 60) -> str:
    """Each signal's value at `start_ns` and its changes up to `end_ns`, as text."""
    h = header(path)
    picked: list[Var] = []
    out: list[str] = []
    for n in names:
        found = resolve(h, n)
        if not found:
            out.append(f"{n}: not in this dump")
        elif len(found) > 1:
            out.append(f"{n}: ambiguous, one of: {', '.join(v.name for v in found[:12])}")
        else:
            picked.append(found[0])
    if not picked:
        return "\n".join(out)
    t0 = int(start_ns / h.ns_per_tick)
    t1 = int(end_ns / h.ns_per_tick) if end_ns is not None else None
    codes = {v.code for v in picked}
    at_start: dict[str, str] = {}
    seen: dict[str, list[tuple[int, str]]] = {c: [] for c in codes}
    for tick, code, value in _changes(path, codes):
        if t1 is not None and tick > t1:
            break
        if tick <= t0:
            at_start[code] = value
        else:
            seen[code].append((tick, value))
    ns = h.ns_per_tick
    for v in picked:
        changes = seen[v.code]
        line = f"{v.name} [{v.width}]: {show(at_start.get(v.code, '?'), v.width)} at {start_ns:g} ns"
        if changes:
            shown = changes[:max_changes]
            line += "; then " + ", ".join(f"{t * ns:g}: {show(val, v.width)}" for t, val in shown)
            if len(changes) > len(shown):
                line += f" … (+{len(changes) - len(shown)} more changes: narrow the window)"
        else:
            line += "; no change" + (f" up to {end_ns:g} ns" if end_ns is not None else "")
        out.append(line)
    return "\n".join(out)


def find(path: Path, name: str, value: str, after_ns: float = 0.0, nth: int = 1) -> str:
    """The time the signal takes `value` (the nth time after `after_ns`), as text."""
    h = header(path)
    found = resolve(h, name)
    if len(found) != 1:
        return f"{name}: not in this dump" if not found else f"{name}: ambiguous, one of: {', '.join(v.name for v in found[:12])}"
    var = found[0]
    want = _normal(value)
    t0 = int(after_ns / h.ns_per_tick)
    count = 0
    for tick, _, val in _changes(path, {var.code}):
        if tick < t0:
            continue
        if _as(val) == want:
            count += 1
            if count >= max(1, nth):
                return f"{var.name} = {show(val, var.width)} at {tick * h.ns_per_tick:g} ns" + (f" (time #{count} after {after_ns:g} ns)" if nth > 1 else "")
    return f"{var.name} never becomes {value} after {after_ns:g} ns" + (f" ({count} time(s) found, {nth} asked)" if count else "") + f" (the dump ends at {h.end_ns():g} ns)"
