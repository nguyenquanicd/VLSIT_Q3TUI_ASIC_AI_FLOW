"""The Tcl script of a VC Static run (after the examples of `doc/vcst/examples/CDC` and `RDC`): analyze, elaborate, the shared SDC, the
resets, the check and the reports. Written by code each run (`build/sanity/<role>_setup.tcl`); `options.extra_tcl` adds lines of your own after the SDC;
`options.blackbox` (module names) makes those modules black boxes before the analysis: a big memory's array (rv32iv_sm's 2 Mbit DMEM) took RDC to
49 GB and crashed it — only its ports matter for crossings."""

from __future__ import annotations

import re
from pathlib import Path

SETUP = """# {role} setup of `{top}`, written by Q3TUI (step {role}) from the RTL and the shared SDC: it is rewritten every run; put lines of your own in options.extra_tcl.
cd {work}
set_app_var enable_{role} true
{blackbox}analyze -format sverilog -vcs "-f {filelist}"
elaborate {top}
read_sdc {sdc}
{groups}{resets}{setup}{extra}{config}check_{role}
{waive}{reports}
quit
"""
REPORTS = {
    "cdc": "report_violations -app CDC -verbose -file {work}/cdc_violations.rpt",
    "rdc": "report_rdc -list -limit 0 -include_compressed -no_summary -hide_id -file {work}/rdc_violations.rpt",
}
CONFIG = {"rdc": "configure_rdc_corrupt -report_rdc_on_cdc true\n"}  # (the tool: RDC on asynchronous paths is off by default)
_LOW = re.compile(r"(^|_)(n|b)$|rst_?n|resetn|^n_", re.I)


def reset_lines(resets: list[str]) -> str:
    """`create_reset` for the resets of constraints/sdc/sdc.json: low-active when the name says so."""
    return "".join(f"create_reset -sense {'low' if _LOW.search(r) else 'high'} {r}\n" for r in resets)


def group_lines(sdc: dict) -> str:
    """Every clock of constraints/sdc/sdc.json its own asynchronous group (what a CDC check needs), unless the SDC groups them already."""
    names = [c["name"] for c in sdc.get("clocks") or []]
    if sdc.get("clock_groups") or len(names) < 2:
        return ""
    return "set_clock_groups -asynchronous " + " ".join(f"-group {{{n}}}" for n in names) + "\n"


def absolute_filelist(filelist: Path, root: Path, work: Path) -> Path:
    """`<work>/rtl_abs.f`: the project's filelist with absolute paths, so the tool can run in the work folder (it writes
    `elab_summary.rpt`, `.vcstPref` and its session folders into its working directory, which must not be the project folder)."""
    out = []
    for line in filelist.read_text().splitlines():
        t = line.strip()
        if not t or t.startswith(("//", "#")):
            out.append(line)
        elif t.startswith("+incdir+"):
            out.append("+incdir+" + str((root / t[len("+incdir+"):]).resolve()))
        elif t.startswith(("+", "-")):
            out.append(line)
        else:
            out.append(str((root / t).resolve()))
    work.mkdir(parents=True, exist_ok=True)
    dest = work / "rtl_abs.f"
    dest.write_text("\n".join(out) + "\n")
    return dest


def blackbox_lines(modules) -> str:
    """`set_blackbox` for the modules of options.blackbox (a list, or names separated by spaces / commas); before analyze (the tool's order)."""
    names = [m for m in (re.split(r"[\s,]+", modules) if isinstance(modules, str) else [str(x) for x in modules or []]) if m.strip()]
    return f"set_blackbox -designs {{{' '.join(dict.fromkeys(n.strip() for n in names))}}}\n" if names else ""


def text(role: str, top: str, root: Path, filelist: Path, work: Path, sdc: Path, sdcj: dict, extra: str = "", waive: Path | None = None,
         blackbox=None, resets: str | None = None, setup: str = "") -> str:
    """The script; `waive`: a file of waiver commands sourced after the check (the run of `<role>_check`); `blackbox`: modules made black boxes;
    `resets`: the `create_reset` lines of the setup step (None: from the SDC's resets); `setup`: the setup step's other commands (lib/setup.py)."""
    return SETUP.format(role=role, work=work, filelist=filelist, top=top, sdc=sdc, groups=group_lines(sdcj), blackbox=blackbox_lines(blackbox),
                        resets=resets if resets is not None else reset_lines(list(sdcj.get("resets") or [])), setup=setup, extra=(extra.rstrip() + "\n") if extra.strip() else "",
                        config=CONFIG.get(role, ""), waive=f"source {waive}\n" if waive else "", reports=REPORTS[role].format(work=work))
