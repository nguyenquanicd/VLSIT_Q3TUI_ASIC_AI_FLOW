"""The ECO flow's Tcl, all written by code: the guard on the netlist edits an LLM proposes (they run in dc_shell: a trust boundary), the
Design Compiler script that applies them to the ORG netlist, the PrimeTime script of the STA and its report readers."""
from __future__ import annotations

import re
from pathlib import Path

from q3tui.flows.asic.lib import dc

# netlist edits Design Compiler takes on a linked netlist (the patch of eco_patch, the timing fixes of eco_sta)
EDIT_COMMANDS = frozenset({
    "create_cell", "remove_cell", "create_net", "remove_net", "connect_net", "disconnect_net", "create_port", "remove_port",
    "size_cell", "change_link", "insert_buffer", "remove_buffer", "set", "puts", "current_instance",
})
# what an edit may ask inside [ … ]: queries only
QUERY_COMMANDS = frozenset({
    "get_cells", "get_nets", "get_pins", "get_ports", "get_lib_cells", "get_lib_pins", "get_object_name", "all_fanin",
    "all_fanout", "get_attribute", "index_collection", "sizeof_collection",
})
_WORD = re.compile(r"^\s*([A-Za-z_][\w:]*)")


def _substitutions(line: str) -> list[str]:
    """The first word of every Tcl command substitution `[ … ]` in the line. A `[` after an odd number of backslashes is a literal
    (an escaped netlist name such as `gen_chan\\[0\\]`), not a command; after an even number (`\\\\[`) it still substitutes."""
    out = []
    for m in re.finditer(r"\[\s*([^\s\]]*)", line):
        k, n = m.start() - 1, 0
        while k >= 0 and line[k] == "\\":
            n, k = n + 1, k - 1
        if n % 2 == 0:
            out.append(m.group(1))
    return out


def check_edits(commands: list[str]) -> list[str]:
    """The problems of LLM-written netlist edits (empty: they may run): one command per line, only `EDIT_COMMANDS`, queries only inside
    brackets, no `;` chaining, no braces (no bodies: loops, procs), no variables but the ones `set` makes."""
    problems = []
    for i, raw in enumerate(commands, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\n" in line or ";" in line:
            problems.append(f"line {i}: one command per line, no `;` ({line[:80]})")
            continue
        if "{" in line or "}" in line:
            problems.append(f"line {i}: no braces (no loops / procs / bodies) ({line[:80]})")
            continue
        m = _WORD.match(line)
        if not m or m.group(1) not in EDIT_COMMANDS:
            problems.append(f"line {i}: `{m.group(1) if m else line[:20]}` is not a netlist edit this flow runs "
                            f"(allowed: {', '.join(sorted(EDIT_COMMANDS))})")
            continue
        for q in _substitutions(line):
            if q not in QUERY_COMMANDS:
                hint = "" if _WORD.match(q) else r" — a bracket in a name (bus bit, generate instance) is escaped: `\[0\]`"
                problems.append(f"line {i}: `[{q} …]` is not a query this flow allows (allowed: {', '.join(sorted(QUERY_COMMANDS))}){hint}")
    return problems


_KEYWORDS = {"module", "endmodule", "input", "output", "inout", "wire", "reg", "assign", "supply0", "supply1", "tri", "parameter", "defparam"}
_INSTANCE = re.compile(r"^\s*([A-Za-z_][\w$]*)\s+(?:#\s*\(.*?\)\s*)?(\\\S+|[A-Za-z_][\w$\[\]]*)\s*\(", re.M)


def cell_types(netlist: str) -> dict[str, int]:
    """{cell (library cell or module): instances} of a gate-level Verilog netlist: the cells an edit can name."""
    out: dict[str, int] = {}
    for m in _INSTANCE.finditer(netlist):
        if m.group(1) not in _KEYWORDS:
            out[m.group(1)] = out.get(m.group(1), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


_LIB_REF = re.compile(r"^\[\s*get_lib_cells\s+(?:\S*/)?([^\s\]/]+)\s*\]$")


def _lib_cell(ref: str) -> str:
    """The library cell an edit names: `X`, `lib/X`, `[get_lib_cells */X]`."""
    m = _LIB_REF.match(ref.strip())
    return m.group(1) if m else ref.strip().rsplit("/", 1)[-1]


_MODULE = re.compile(r"(?ms)^\s*module\s+([A-Za-z_][\w$]*)\b(.*?)^\s*endmodule")


def _hierarchy(netlist: str) -> tuple[str, dict[str, dict[str, str]]]:
    """(top module, {module: {instance: cell or module}}) of a gate-level netlist; instance names without the escape `\\`."""
    mods = {m.group(1): {i.group(2).lstrip("\\"): i.group(1) for i in _INSTANCE.finditer(m.group(2)) if i.group(1) not in _KEYWORDS}
            for m in _MODULE.finditer(netlist)}
    used = {t for insts in mods.values() for t in insts.values()}
    tops = [m for m in mods if m not in used]
    return (tops[-1] if tops else ""), mods


def _has_instance(tree: tuple[str, dict[str, dict[str, str]]], path: str) -> bool:
    """An instance path as a Design Compiler edit names it (`u_core/U12`, `u_core/g\\[0\\].u/U3`), from the top down the hierarchy."""
    top, mods = tree
    parts = path.replace("\\[", "[").replace("\\]", "]").split("/")
    cur = top
    for k, name in enumerate(parts):
        insts = mods.get(cur, {})
        if name not in insts:
            return False
        if k < len(parts) - 1:
            cur = insts[name]
    return True


def check_structure(commands: list[str], netlist: str) -> list[str]:
    """What the edits do to the netlist, checked before Design Compiler runs them: the library cells they name are cells the netlist
    already uses, the instances they touch exist (or are created by them), a created cell and a created net get connected."""
    lib = set(cell_types(netlist))
    problems: list[str] = []
    created_cells: dict[str, int] = {}
    created_nets: dict[str, int] = {}
    touched: list[tuple[int, str]] = []  # (line, instance) an edit needs to exist
    connected: set[str] = set()  # nets and instances some connect_net reaches
    for i, raw in enumerate(commands, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cmd, *args = re.findall(r"\[[^\]]*\]|\S+", line)
        if cmd in ("create_cell", "size_cell", "insert_buffer", "change_link") and len(args) >= 2:
            cell = _lib_cell(args[-1])
            if cell not in lib:
                what = "a placeholder" if "placeholder" in cell.lower() else "not a library cell this netlist uses"
                problems.append(f"line {i}: `{cell}` is {what} (use one of the cells listed in the task)")
            if cmd == "create_cell":
                created_cells[args[0]] = i
            elif cmd != "insert_buffer":
                touched.append((i, args[0]))
        elif cmd == "create_net" and args:
            created_nets[args[0]] = i
        elif cmd in ("connect_net", "disconnect_net") and len(args) >= 2:
            for pin in args[1:]:
                if "/" in pin and not pin.startswith("["):
                    touched.append((i, pin.rsplit("/", 1)[0]))
                    if cmd == "connect_net":
                        connected |= {args[0], pin.rsplit("/", 1)[0]}
        elif cmd == "remove_cell" and args:
            touched.append((i, args[0]))
    tree = _hierarchy(netlist)
    problems += [f"line {i}: instance `{inst}` is not in the netlist" for i, inst in touched
                 if inst not in created_cells and not _has_instance(tree, inst)]
    problems += [f"line {i}: the new cell `{c}` is never connected (connect_net <net> {c}/<pin>)" for c, i in created_cells.items() if c not in connected]
    problems += [f"line {i}: the new net `{n}` is never connected" for n, i in created_nets.items() if n not in connected]
    return problems


def edits_text(commands: list[str], title: str) -> str:
    return f"# generated by Q3TUI — {title}\n" + "\n".join(c.strip() for c in commands if c.strip()) + "\n"


def _q(paths) -> str:
    return " ".join(f'"{x}"' for x in paths)


def apply_script(libs: list[str], netlist: Path, top: str, edits: list[Path], out: Path, workdir: Path) -> str:
    """Design Compiler: the ORG netlist read and linked, the edit files sourced in order, check_design, the Post NETLIST written. No compile:
    the netlist is changed only where the edits say."""
    lines = [f"# generated by Q3TUI (eco_apply) — top {top}",
             "set_app_var sh_continue_on_error false",
             f"set_app_var target_library [list {_q(libs)}]",
             f'set_app_var link_library [list "*" {_q(libs)}]',
             f'read_verilog -netlist "{netlist}"',
             f"current_design {top}",
             "link"]
    lines += [f'source -echo -verbose "{e}"' for e in edits]
    lines += [f'redirect "{workdir / "check_design.rpt"}" {{ check_design }}',
              f'file mkdir "{out.parent}"',
              f'write -format verilog -hierarchy -output "{out}"',
              'puts "Q3TUI_ECO_APPLY: DONE"',
              "exit"]
    return "\n".join(lines) + "\n"


def apply_errors(log: str) -> list[str]:
    """The error lines of the Design Compiler run (an edit that names a cell / net / pin that is not there, a lib cell unknown, …)."""
    return [ln.strip() for ln in log.splitlines() if re.match(r"^\s*Error:", ln)][:30]


def sta_script(libs: list[str], netlist: Path, top: str, sdc: Path | None, workdir: Path, max_paths: int = 10) -> str:
    """PrimeTime: the Post NETLIST linked with the libraries, the constraints, setup and hold paths, all violators, the global summary."""
    out = lambda n: f'"{workdir / n}"'  # noqa: E731
    lines = [f"# generated by Q3TUI (eco_sta) — top {top}",
             f'set_app_var link_path [list "*" {_q(libs)}]',
             f'read_verilog "{netlist}"',
             f"link_design {top}"]
    if sdc is not None:
        lines.append(f'read_sdc -echo "{sdc}"' if sdc.suffix == ".sdc" else f'source -echo "{sdc}"')
    # (-slack_lesser_than: PrimeTime may list only violators, "No paths with slack less than 0.00" leaves no worst path to read)
    lines += ["update_timing -full",
              f"redirect {out('sta_setup.rpt')} {{ report_timing -delay_type max -slack_lesser_than 1e30 -max_paths {max_paths} -nworst 1 -path_type full -nets -input_pins }}",
              f"redirect {out('sta_hold.rpt')} {{ report_timing -delay_type min -slack_lesser_than 1e30 -max_paths {max_paths} -nworst 1 -path_type full }}",
              f"redirect {out('sta_constraints.rpt')} {{ report_constraint -all_violators }}",
              f"redirect {out('sta_global.rpt')} {{ report_global_timing }}",
              f"redirect {out('sta_check_timing.rpt')} {{ check_timing }}",
              'puts "Q3TUI_STA: DONE"',
              "exit"]
    return "\n".join(lines) + "\n"


def sta_result(setup: str, hold: str, constraints: str) -> dict:
    """{setup: {met, slack_ns, startpoint, endpoint}, hold: {…}, violations: [{group, line, slack_ns}], setup_ok} from the PrimeTime reports
    (their path format is Design Compiler's: `dc.parse_timing` reads both)."""
    s, h = dc.parse_timing(setup), dc.parse_timing(hold)
    items = dc.violation_items(constraints)
    return {"setup": s, "hold": h, "violations": items,
            "setup_violations": [v for v in items if v["group"].startswith(("max_delay", "setup"))],
            "hold_violations": [v for v in items if v["group"].startswith(("min_delay", "hold"))],
            "setup_ok": bool(s) and s.get("met", False)}
