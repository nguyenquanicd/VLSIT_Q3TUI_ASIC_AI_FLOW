"""Mermaid as the TUI draws it: the form termaid reads, and the notes printed under a state machine (from the old
Q3TUI)."""

from __future__ import annotations

import re

_SUBGRAPH = re.compile(r"^(\s*subgraph\s+[\w-]+)(?=\[)", re.MULTILINE)


def normalize_mermaid(source: str) -> str:
    """Mermaid as models write it, in the form termaid reads: `subgraph id["label"]` → `subgraph id ["label"]` (else the
    id is read as `id["label` and the label drawn as `id["label"]`)."""
    return _SUBGRAPH.sub(r"\1 ", source)


_STADIUM = re.compile(r"(?<![\w-])([A-Za-z_]\w*)\(\[(.*?)\]\)")
_FLAG = re.compile(r"(?<![\w-])([A-Za-z_]\w*)>([^\]\n]*)\]")
_START = re.compile(r"^\s*\[\*\]\s*-->\s*([A-Za-z_]\w*)\s*(?::\s*(.*?))?\s*$")


def display_mermaid(source: str) -> tuple[str, list[str]]:
    """A diagram as it is drawn (the spec keeps the standard form) and the notes to print under it. A state machine's
    initial `[*] --> S` is not drawn as a start node with an arrow: S itself says it is where reset goes (`S (reset)`,
    or the transition's label). A transition three or more states take the same way (abort …) is not drawn from each:
    it becomes a note "from any state: abort → IDLE"."""
    source = normalize_mermaid(source)
    lines = source.splitlines()
    head = next((i for i, ln in enumerate(lines) if ln.strip() and not ln.strip().startswith("%%")), None)
    if head is not None and lines[head].strip().startswith(("flowchart", "graph")):
        # IO drawn as rounded boxes: termaid draws a stadium `([…])` with a column of brackets and a flag `>…]` lopsided
        source = _STADIUM.sub(r"\1(\2)", source)
        return _FLAG.sub(r"\1(\2)", source), []
    if head is None or not lines[head].strip().startswith("stateDiagram"):
        return source, []
    notes: list[str] = []
    g = _graph(source, "fsm")
    if g is not None:
        common: dict[tuple[str, str], set[str]] = {}
        for e in g.edges:
            if e.label.strip() and not e.source.startswith("[*]"):
                common.setdefault((e.target, " ".join(e.label.split())), set()).add(e.source)
        for (target, label), sources in common.items():
            if len(sources) < 3:
                continue
            alternatives = "|".join(map(re.escape, sources))
            label_re = r"\s+".join(map(re.escape, label.split()))
            edge = re.compile(rf"^\s*({alternatives})\s*-->\s*{re.escape(target)}\s*:\s*{label_re}\s*$")
            lines = [ln for ln in lines if not edge.match(ln)]
            notes.append(f"from any state: {label} → {target}")
    starts, depth = [], 0
    for i, ln in enumerate(lines):
        if depth == 0 and (m := _START.match(ln)):
            starts.append((i, m))
        depth += ln.count("{") - ln.count("}")
    if len(starts) != 1:
        return "\n".join(lines), notes
    at, m = starts[0]
    state, why = m.group(1), (m.group(2) or "reset").strip()
    if re.search(rf"^\s*state\s+{state}\s*\{{", source, re.MULTILINE):  # a composite state keeps its start node
        return "\n".join(lines), notes
    rest = [ln for i, ln in enumerate(lines) if i != at]
    decl = re.compile(rf'^\s*state\s+"([^"]*)"\s+as\s+{state}\s*$')
    label = next((d.group(1) for ln in rest if (d := decl.match(ln))), state)
    rest = [ln for ln in rest if not decl.match(ln)]
    rest.insert(head + 1, f'  state "{label} ({why})" as {state}')  # declared first: drawn on top
    return "\n".join(rest), notes


def _graph(source: str, kind: str):
    """termaid's graph of a Mermaid diagram, or None when termaid is missing / cannot read it."""
    source = normalize_mermaid(source)
    try:
        if kind == "fsm":
            from termaid.parser.statediagram import parse_state_diagram

            return parse_state_diagram(source)
        from termaid.parser.flowchart import parse_flowchart

        return parse_flowchart(source)
    except Exception:  # noqa: BLE001 - an unreadable diagram is reported by the caller
        return None
