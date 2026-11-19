"""Task `edit` of eco_rtl (external mode: a copy of the ORG RTL in `eco/rtl/`; or RTL that is your own, not the rtl flow's): code applies
the plan's exact RTL edits (`rtl_edits`: old → new, no LLM rewrites them); an LLM stage edits RTL(F) only for a change you chose in other
words, or when an edit does not fit the file. A parse error goes back to the LLM once."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_rtl.tasks.check import parse_errors
from q3tui.flows.eco.eco_rtl.tasks.plan import denied, edits_text, spec_part
from q3tui.flows.eco.lib.base import task_prompt
from q3tui.flows.eco.lib.models import RtlUpdate
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("edit", "external mode or your own RTL: the AI edits RTL(F) itself")
PROMPT = task_prompt(__file__)


def apply_rtl_edits(root: Path, mapping: dict, rtl_edits: list[dict]) -> list[str]:
    """The plan's exact edits applied to the RTL(F) files (all or none); the problems when one does not fit (file unknown, `old` not once)."""
    files = [Path(f) for f in mapping]
    problems, todo = [], []
    for e in rtl_edits:
        name = Path(e["file"]).name
        hits = [f for f in files if str(f) == e["file"].lstrip("./")] or [f for f in files if f.name == name or mapping[str(f)].endswith("/" + name)]
        if len(hits) != 1:
            problems.append(f"`{e['file']}` is {'not' if not hits else 'more than one'} RTL(F) file")
            continue
        todo.append((root / hits[0], e))
    texts: dict[Path, str] = {}
    for path, e in todo:
        text = texts.setdefault(path, path.read_text(errors="replace"))
        n = text.count(e["old"]) if e["old"] else 0
        if n != 1:
            problems.append(f"in {e['file']}: the text to replace occurs {n} times (not once): {e['old'][:120]!r}")
            continue
        texts[path] = text.replace(e["old"], e["new"])
    if not problems:
        for path, text in texts.items():
            path.write_text(text)
    return problems


async def _edit(step, ctx: StepContext, task: str) -> RtlUpdate:
    engine, project = ctx.engine, ctx.project
    stage = Stage(name="eco_rtl", system_prompt=PROMPT, prompt=task, cwd=project.root,
                  builtin_tools=["Read", "Grep", "Glob", "Edit", "Write"], output_model=RtlUpdate,
                  write_dirs=[step.rtl_f_dir(engine)],
                  deny_dirs=denied(step, engine))
    return (await ctx.llm(stage)).output


async def run(step, ctx: StepContext, req: Path, mapping: dict, feedback: list[str], update: bool, change: str,
              exact: list[dict] | None = None) -> RtlUpdate:
    """RTL(F) edited here: the plan's exact edits applied by code; else — your own way, or an edit that does not fit — the LLM edits it."""
    project = ctx.project
    if exact:
        misfit = apply_rtl_edits(project.root, mapping, exact)
        if not misfit:
            out = RtlUpdate(summary=change, changes=[{"file": e["file"], "what": "the plan's exact edit"} for e in exact])
            problems = parse_errors(step, ctx.engine)
            if not problems:
                step.task(ctx, "edit", f"the plan's {len(exact)} exact edit(s), applied as they are")
                return out
            change = f"{change}\n\nThe exact edits (applied):\n{edits_text(exact)}"
            out = await _edit(step, ctx, "\n".join([f"## RTL(F): files {', '.join(mapping)}", "## The change made", change, "",
                                                    "## RTL(F) does not parse — fix these errors (only them)", *problems[:20]]))
            problems = parse_errors(step, ctx.engine)
            if problems:
                step.task(ctx, "edit", "; ".join(problems[:3]), "failed")
                raise StepFailed("RTL(F) does not parse: " + "; ".join(problems[:5]))
            step.task(ctx, "edit", f"the plan's {len(exact)} exact edit(s), then AI: parse errors fixed")
            return out
        ctx.emit("warning", message=f"RTL(F): the plan's edits do not fit the files ({misfit[0]}): the AI makes them")
        change = f"{change}\n\nMake exactly these edits (they did not fit the files as written: {'; '.join(misfit[:3])}):\n{edits_text(exact)}"
    task = [f"## The requirement ({project.rel(req)})", req.read_text(errors="replace"), "", *spec_part(step, ctx.engine),
            f"## RTL(F): edit these files in place (top `{step.top(ctx.engine)}`; each is named after its ORG file)",
            *[f"- {f} (ORG: {o})" for f, o in mapping.items()]]
    if update:
        task += ["", "## Change requests on the current RTL(F)", *[f"- {x}" for x in feedback],
                 "", f"The changes made so far against the ORG RTL are in {project.rel(step.rtl_diff(ctx.engine))}."]
    task += ["", "## The change to make (planned, and decided with the user when it differs from the request)", change,
             "Make this change and nothing more."]
    out = await _edit(step, ctx, "\n".join(task))
    problems = parse_errors(step, ctx.engine)
    if problems:  # one round back to the LLM with the parser's errors
        out = await _edit(step, ctx, "\n".join([*task, "", "## RTL(F) does not parse — fix these errors (only them)", *problems[:20]]))
        problems = parse_errors(step, ctx.engine)
        if problems:
            step.task(ctx, "edit", "; ".join(problems[:3]), "failed")
            raise StepFailed("RTL(F) does not parse: " + "; ".join(problems[:5]))
    step.task(ctx, "edit", f"{out.summary} ({len(out.changes)} file(s))")
    return out
