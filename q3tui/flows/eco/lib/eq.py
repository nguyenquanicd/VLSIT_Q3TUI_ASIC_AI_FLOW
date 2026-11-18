"""EQ(1) and EQ(2): a Formality run (the asic flow's script and reader) and, when it is not equivalent, an LLM's reading of why."""
from __future__ import annotations

import shutil
from pathlib import Path

from q3tui.flows.asic.lib import fm
from q3tui.flows.eco.lib.models import EqAdvice
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepFailed


async def run_formality(step, ctx, ref_files: list[Path], netlist: Path, tag: str) -> dict:
    """RTL `ref_files` (reference) against `netlist` (implementation) with the flow's libraries and the SVF of the ORG synthesis when
    there is one (ref/<name>/netlist/<top>.svf: without it Formality cannot match DC's register merges / FSM recoding; the ECO edits leave it valid).
    The report and the log are kept in eco/reports/<tag>_lec.rpt / <tag>_fm.log. Returns fm.parse_result + where they are."""
    engine, project = ctx.engine, ctx.project
    top = step.top(engine)
    libs = step.need_libraries(engine)
    tools = await step.need_tool(engine, "asic_lec", "module synopsys/formality")
    work = step.build_dir(engine)
    for n in ("lec.rpt", "fm.log"):
        (work / n).unlink(missing_ok=True)
    script = work / "lec.tcl"
    svf = step.org_svf(engine)
    script.write_text(fm.script_text(ref_files, top, libs, netlist, svf if svf.is_file() else None, work, step.options))
    ctx.emit("log", message=f"{tag}: Formality, {len(ref_files)} RTL file(s) against {project.rel(netlist)}…")
    step.top_name = top
    res, log = await step.run_tool(tools, "asic_lec", script, work, "fm.log")
    result = fm.parse_result(log)
    rep = step.reports_dir(engine)
    rep.mkdir(parents=True, exist_ok=True)
    if (work / "lec.rpt").is_file():
        shutil.copyfile(work / "lec.rpt", rep / f"{tag}_lec.rpt")
    (rep / f"{tag}_fm.log").write_text(log)
    result.update(report=project.rel(rep / f"{tag}_lec.rpt"), log=project.rel(rep / f"{tag}_fm.log"))
    if result.get("unsuppressed"):
        raise StepFailed(f"{tag}: Formality stopped reading the RTL on {', '.join(result['unsuppressed'])} (see {result['log']}): fix the RTL, "
                         f"or accept it with options.message_filter: [{result['unsuppressed'][0]}] of {step.name}")
    if result["status"] == "unknown":
        from q3tui.eda import tools as toolmod
        toolmod.check_broken(res, "asic_lec")
        raise StepFailed(f"{tag}: Formality gave no verdict (log: {result['log']})")
    return result


async def advise(step, ctx, system: str, task: str, read: list[Path]) -> EqAdvice:
    """A read-only LLM stage: why the check failed and what to do (the files of `read` named in the task)."""
    project = ctx.project
    files = "\n".join(f"- {project.rel(p)}" for p in read if p.is_file())
    stage = Stage(name=f"{step.name}_advice", system_prompt=system, cwd=project.root, builtin_tools=["Read", "Grep", "Glob"],
                  prompt=f"{task}\n\nFiles to read:\n{files}", output_model=EqAdvice)
    return (await ctx.llm(stage)).output


def advice_md(title: str, result: dict, advice: EqAdvice | None) -> str:
    lines = [f"# {title}", "", f"- Status: **{result.get('status', '?')}**",
             f"- Failing points: {result.get('failing', '?')}, passing: {result.get('passing', '?')}, unmatched: {result.get('unmatched', '?')}",
             f"- Report: `{result.get('report', '')}`, log: `{result.get('log', '')}`", ""]
    if advice:
        lines += ["## Summary", "", advice.summary, "", f"Owner of the fix: **{advice.owner}**", ""]
        if advice.fix:
            lines += ["## Recommended fix", "", advice.fix, ""]
        if advice.causes:
            lines += ["## Causes", ""]
            for c in advice.causes:
                lines += [f"- **{c.what}**" + (f"\n  - evidence: `{c.evidence.strip()}`" if c.evidence.strip() else "")
                          + f"\n  - recommendation: {c.recommendation}"]
    return "\n".join(lines) + "\n"
