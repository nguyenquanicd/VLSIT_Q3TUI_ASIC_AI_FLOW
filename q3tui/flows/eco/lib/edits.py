"""An LLM stage that writes netlist edits (the ECO patch, a timing fix): read-only, its answer checked by code (`tcl.check_edits`) and sent back
once with the problems, then the step fails."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.lib import liberty, tcl
from q3tui.flows.eco.lib.models import NetlistEdits
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepFailed


def cells_block(netlist: Path, libs: list[str] = (), limit: int = 60) -> str:
    """The library cells the netlist uses (the ones an edit may use), with what each computes when the .lib is there (liberty.py)."""
    cells = tcl.cell_types(netlist.read_text(errors="replace")) if netlist.is_file() else {}
    if not cells:
        return ""
    used = list(cells.items())[:limit]
    info = liberty.cells(list(libs), [c for c, _ in used]) if libs else {}
    if not info:
        items = ", ".join(f"{c} ({n})" for c, n in used)
        return f"Cells the netlist instantiates (library cells you can use, with their count): {items}"
    return "\n".join(["Cells the netlist instantiates (the only library cells you can use), with their count and, from the library, the "
                      "function of each output (`!` not, a space or `*` and, `+` or, `^` xor) — use these, never a guess from the name:",
                      *[f"- {liberty.line(c, info[c])} [{n}]" if c in info else f"- {c} [{n}]" for c, n in used]])


def lib_pins(netlist: Path | None, libs: list[str]) -> dict[str, set[str]]:
    """{library cell: its pins} of the cells the netlist uses, from the .lib ({} without it)."""
    if not libs or netlist is None or not netlist.is_file():
        return {}
    return {c: set(i["pins"]) for c, i in liberty.cells(list(libs), tcl.cell_types(netlist.read_text(errors="replace"))).items()}


def _problems(commands: list[str], netlist: Path | None, libs: list[str] = ()) -> list[str]:
    """Refused edits: not allowed commands (check_edits), nothing to do, or edits that do not fit the netlist (check_structure)."""
    problems = tcl.check_edits(commands) or ([] if any(c.strip() for c in commands) else ["no command"])
    if not problems and netlist is not None and netlist.is_file():
        problems = tcl.check_structure(commands, netlist.read_text(errors="replace"), lib_pins(netlist, libs))
    return problems


def _qualified(ctx, out: NetlistEdits, netlist: Path | None) -> NetlistEdits:
    """The edits with each existing instance / net named from the top where it has exactly one place (tcl.qualify)."""
    if netlist is None or not netlist.is_file():
        return out
    commands, notes = tcl.qualify(out.commands, netlist.read_text(errors="replace"))
    if notes:
        ctx.emit("log", message=f"named from the top: {len(notes)} object(s) ({', '.join(notes[:3])}{' …' if len(notes) > 3 else ''})")
    return out.model_copy(update={"commands": commands})


def checked(ctx, commands: list[str], netlist: Path, libs: list[str] = ()) -> tuple[list[str], list[str]]:
    """(the edits named from the top where they can be, what is wrong with them): the check of any netlist edits, the plan's or the patch's."""
    out = _qualified(ctx, NetlistEdits(commands=list(commands)), netlist)
    return out.commands, _problems(out.commands, netlist, libs)


async def write_edits(step, ctx, name: str, system: str, task: str, deny: list[Path], netlist: Path | None = None) -> NetlistEdits:
    project = ctx.project
    stage = Stage(name=name, system_prompt=system, prompt=task, cwd=project.root, builtin_tools=["Read", "Grep", "Glob"],
                  output_model=NetlistEdits, deny_dirs=deny)
    libs = step.libraries(ctx.engine)
    out: NetlistEdits = _qualified(ctx, (await ctx.llm(stage)).output, netlist)
    problems = _problems(out.commands, netlist, libs)
    if problems:
        stage = Stage(name=name, system_prompt=system, cwd=project.root, builtin_tools=["Read", "Grep", "Glob"], output_model=NetlistEdits,
                      deny_dirs=deny, prompt=task + "\n\n## Your previous answer was refused — fix these problems\n"
                      + "\n".join(f"- {p}" for p in problems) + "\n\nPrevious commands:\n" + "\n".join(out.commands))
        out = _qualified(ctx, (await ctx.llm(stage)).output, netlist)
        problems = _problems(out.commands, netlist, libs)
        if problems:
            raise StepFailed(f"{name}: the netlist edits are refused: " + "; ".join(problems[:5]))
    return out
