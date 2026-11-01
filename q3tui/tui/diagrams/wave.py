"""WaveJSON (wavedrom) blocks as terminal art: one row per lane, a cycle ruler on top (from the old Q3TUI)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache


def loads_json5(text: str):
    """WaveJSON as models and people write it (JSON5: unquoted keys, single quotes, comments, trailing commas) → data."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j, buf = i + 1, []
            while j < n and text[j] != c:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                buf.append('\\"' if text[j] == '"' else text[j])
                j += 1
            out.append('"' + "".join(buf).replace("\\'", "'") + '"')
            i = j + 1
        elif text.startswith("//", i):
            i = text.find("\n", i) if "\n" in text[i:] else n
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c.isalpha() or c == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            word = text[i:j]
            out.append(word if word in ("true", "false", "null") else json.dumps(word))
            i = j
        elif c == ",":
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j >= n or text[j] not in "]}":  # a trailing comma is dropped
                out.append(c)
            i += 1
        else:
            out.append(c)
            i += 1
    return json.loads("".join(out))


_WAVE_CHARS = set("pPnNlLhH01=23456789xXzud.|")
_DATA = set("=23456789")


@dataclass
class Lane:
    name: str
    cells: list[tuple[str, str]]  # (state, label) per cycle; state: 0 1 x z p n data gap; label only on a data cell's first cycle


def wave_lanes(source: str) -> list[Lane]:
    """The lanes of a WaveJSON block (groups flattened, spacers dropped). Raises ValueError when it cannot be read."""
    try:
        data = loads_json5(source)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"not valid WaveJSON ({exc})") from None
    if not isinstance(data, dict) or not isinstance(data.get("signal"), list):
        raise ValueError("WaveJSON needs a top-level object with a `signal` list")
    lanes: list[Lane] = []

    def walk(items: list) -> None:
        for it in items:
            if isinstance(it, list):  # a group: ["name", lane, lane ...]
                walk([x for x in it[1:]])
            elif isinstance(it, dict) and "wave" in it:
                lanes.append(_lane(str(it.get("name", "")), str(it["wave"]), it.get("data")))

    walk(data["signal"])
    return lanes


def _lane(name: str, wave: str, data) -> Lane:
    labels = data.split() if isinstance(data, str) else [str(x) for x in data] if isinstance(data, list) else []
    cells: list[tuple[str, str]] = []
    prev = "x"
    k = 0
    for ch in wave:
        if ch in ".|":
            st = prev if prev not in ("data",) else "data+"
            cells.append(("gap" if ch == "|" else st, ""))
            continue
        if ch in _DATA:
            st, label = "data", (labels[k] if k < len(labels) else "")
            k += 1
        else:
            st, label = {"p": "p", "P": "p", "n": "n", "N": "n", "h": "1", "H": "1", "l": "0", "L": "0", "1": "1", "0": "0",
                         "x": "x", "X": "x", "z": "z", "u": "1", "d": "0"}.get(ch, "x"), ""
        cells.append((st, label))
        prev = st
    return Lane(name, cells)


def check_wave(source: str, known_names: set[str] | None = None) -> list[str]:
    """Problems of one WaveJSON block: unreadable, unknown wave characters, data labels that do not match the data
    cycles, and (with `known_names`) signals the rest of the spec never names."""
    try:
        data = loads_json5(source)
    except (ValueError, json.JSONDecodeError) as exc:
        return [f"timing diagram is not valid WaveJSON ({exc})"]
    if not isinstance(data, dict) or not isinstance(data.get("signal"), list):
        return ["timing diagram needs a top-level object with a `signal` list"]
    problems: list[str] = []
    raw: list[dict] = []

    def walk(items: list) -> None:
        for it in items:
            if isinstance(it, list):
                walk(it[1:])
            elif isinstance(it, dict) and "wave" in it:
                raw.append(it)

    walk(data["signal"])
    if not raw:
        problems.append("timing diagram has no signal lanes")
    for it in raw:
        name, wave = str(it.get("name", "")), str(it["wave"])
        bad = sorted({c for c in wave if c not in _WAVE_CHARS})
        if bad:
            problems.append(f"timing diagram: lane `{name}` has unknown wave characters {' '.join(bad)}")
        need = sum(c in _DATA for c in wave)
        d = it.get("data")
        have = len(d.split()) if isinstance(d, str) else len(d) if isinstance(d, list) else 0
        if need and have != need:
            problems.append(f"timing diagram: lane `{name}` has {need} data cycle(s) but {have} data label(s)")
        if known_names is not None and name and _ident(name) and _ident(name) not in known_names:
            problems.append(f"timing diagram: signal `{name}` is not named anywhere else in the spec (use the port / signal names)")
    return problems


def _ident(name: str) -> str:
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)", name)
    return m.group(1) if m else ""


_GLYPH = {"1": "▔", "0": "▁", "z": "─", "x": "╳", "gap": "≈"}


@lru_cache(maxsize=64)
def wave_text(source: str) -> str | None:
    """A WaveJSON block as terminal art (one row per lane, a cycle ruler on top), or None when it cannot be read."""
    try:
        lanes = wave_lanes(source)
    except ValueError:
        return None
    if not lanes:
        return None
    labels = [lab for ln in lanes for _, lab in ln.cells if lab]
    w = max(4, *(len(lab) + 2 for lab in labels)) if labels else 4
    namew = max(len(ln.name) for ln in lanes)
    cycles = max(len(ln.cells) for ln in lanes)
    rows = [" " * (namew + 1) + "".join(str(c).ljust(w) for c in range(cycles)).rstrip()]
    for ln in lanes:
        out, level = [], None
        for st, lab in ln.cells:
            if st == "p":
                cell, level = "╱" + "▔" * (w // 2 - 1) + "╲" + "▁" * (w - w // 2 - 1), "0"
            elif st == "n":
                cell, level = "╲" + "▁" * (w // 2 - 1) + "╱" + "▔" * (w - w // 2 - 1), "1"
            elif st == "data":
                cell, level = "╳" + lab[: w - 1].center(w - 1, " "), "data"
            elif st == "data+":
                cell = " " * w
            elif st == "gap":
                cell = "≈" + (out[-1][-1] if out else " ") * (w - 1)
            else:
                glyph = _GLYPH[st]
                edge = {("0", "1"): "╱", ("1", "0"): "╲"}.get((level, st), glyph if st in ("0", "1") else "")
                if st in ("0", "1") and level not in ("0", "1", "z", None):
                    edge = "╳"
                cell, level = (edge + glyph * (w - len(edge))) if edge else glyph * w, st
            out.append(cell)
        rows.append(ln.name.rjust(namew) + " " + "".join(out))
    return "\n".join(r.rstrip() for r in rows)
