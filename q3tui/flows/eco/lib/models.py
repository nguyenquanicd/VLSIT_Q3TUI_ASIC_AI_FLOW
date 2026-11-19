"""What the ECO flow's LLM stages answer (pydantic: `Stage.output_model`); code checks and writes every file from them."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Cause(BaseModel):
    what: str = Field(description="What does not match, in one sentence (the compare point / signal / module)")
    evidence: str = Field("", description="The report or log line(s) that show it")
    recommendation: str = Field(description="What to do about it (who changes what)")


class EqAdvice(BaseModel):
    """EQ(1) / EQ(2) not equivalent: why, and what to do."""
    summary: str = Field(description="The verdict in two sentences at most")
    causes: list[Cause] = Field(default_factory=list)
    owner: Literal["rtl", "patch", "netlist", "setup", "unclear"] = Field(
        "unclear", description="Where the fix belongs: rtl (RTL(F) does not do what the requirement asks, or the change is wrong), patch (the "
                               "netlist edits do not implement the RTL change), netlist (the ORG netlist itself), setup (libraries, black boxes, "
                               "constants, Formality settings), unclear")
    fix: str = Field("", description="The concrete fix request for the owner (empty when unclear)")


class FileChange(BaseModel):
    file: str = Field(description="The RTL(F) file changed (project-relative)")
    what: str = Field(description="What changed in it and why (which requirement)")


class RtlUpdate(BaseModel):
    """eco_rtl: the RTL(F) files were edited in place."""
    summary: str = Field(description="The change in a few sentences: what the requirement asks and how the RTL now does it")
    changes: list[FileChange] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list, description=(
        "Anything the requirement leaves open, or a risk of the change. Each one is asked to the user as a question (keep the change, "
        "or their answer): one short self-contained point each, saying what you assumed"))


class RtlAlternative(BaseModel):
    """A smaller change than the one the requirement / change request prescribes, with the same required function."""
    change: str = Field(description="The smaller change: which signals / lines, and what they become")
    smaller_because: str = Field(description="Why it is smaller in the netlist (fewer gates / no new flop / fewer signals touched …)")
    same_function_because: str = Field(description="Why the function the requirement needs is the same, corner cases included")
    differs_from_request: str = Field(description="What it does differently from what was asked (the user decides on this)")


class RtlEdit(BaseModel):
    """One exact RTL edit: `old`, copied from the file, becomes `new` (code applies it: no one rewrites it)."""
    file: str = Field(description="The RTL file, as the task lists it")
    old: str = Field(description="The exact text to replace, copied from the file (whole lines, indentation kept); it must occur once in the file")
    new: str = Field(description="The text it becomes")


class RtlPlan(BaseModel):
    """eco_rtl, before any edit (read-only): the smallest change in the ORG netlist that meets the requirement, found in the netlist itself,
    and the RTL change that mirrors it."""
    requested: str = Field("", description="How the requirement / change requests say to make the change, when they prescribe one; empty when "
                                           "they only state the function")
    netlist_edits: list[str] = Field(default_factory=list, description=(
        "The smallest netlist change as Design Compiler netlist-edit commands on the ORG netlist, one per item, in order (the forms of the "
        "task; every instance / net / pin by its path from the top: u_core/U12/ZN; every instance of replicated logic written out). They are "
        "checked against the netlist and become the ECO patch. Empty only for \"No RTL change:\""))
    rtl_edits: list[RtlEdit] = Field(default_factory=list, description=(
        "The RTL change that mirrors `netlist_edits` (the same structure at the same point), as exact edits: code applies them to the RTL as "
        "they are. Empty only for \"No RTL change:\""))
    plan: str = Field(description="One or two sentences: what the change does (the edits are in `rtl_edits`); or \"No RTL change: <why>\"")
    modules: list[str] = Field(default_factory=list, description="The names of the modules (as in `module <name>`) the change edits")
    netlist_impact: str = Field(description="One line: what the netlist change is (cells, rewired pins, new flops / ports if any)")
    alternative: RtlAlternative | None = Field(None, description="Only when the request prescribes a way and a smaller change gives the same "
                                                                 "required function; else null")


class NetlistEdits(BaseModel):
    """eco_patch / eco_sta: netlist edits for Design Compiler."""
    commands: list[str] = Field(description="One Design Compiler netlist-edit command per item, in the order to run them (create_cell, "
                                            "remove_cell, create_net, remove_net, connect_net, disconnect_net, create_port, size_cell, "
                                            "change_link, insert_buffer, remove_buffer; queries only inside [ ]: get_cells, get_nets, "
                                            "get_pins, get_ports, get_lib_cells). No loops, procs, braces, `;`, files or shell")
    notes: str = Field("", description="Why these edits implement the change: the cells / nets touched and the logic they make")
