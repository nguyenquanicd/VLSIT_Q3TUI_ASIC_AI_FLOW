"""Task `inputs` of eco_inputs: which ORG RTL (a filelist), ORG netlist and requirement the ECO works on. Paths set in the step's options are
used as they are; otherwise the step asks you (ECOIN): the defaults (what the asic flow leaves) or your own paths."""
from __future__ import annotations

import re

from q3tui.flows.eco.lib.base import DEFAULTS, answer_is
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("inputs", "the ORG RTL filelist, the ORG netlist and the requirement: your paths or the asic flow's (ECOIN)")
KEYS = ("rtl", "netlist", "requirement")
USE_DEFAULTS = "Use the defaults"
OWN_PATHS = "My own paths: rtl=<filelist.f> netlist=<netlist.v> requirement=<file.md>"
REQUIREMENT_STUB = """# ECO requirement

Write here what the ECO must change in the design: the behaviour wanted, the signals / modules concerned, and how to check it.
"""


def parse_paths(text: str) -> dict[str, str]:
    """`rtl=… netlist=… requirement=…` (spaces, commas or semicolons between them) from your answer."""
    return {k.lower(): v.strip().strip("\"'") for k, v in re.findall(r"\b(rtl|netlist|requirement)\s*[=:]\s*(\"[^\"]+\"|'[^']+'|[^\s,;]+)", text, re.I)}


def chosen(step, engine) -> tuple[dict[str, str] | None, str]:
    """(the three paths, how they were chosen), or (None, "") while your answer is awaited."""
    top = step.top(engine) or "top"
    defaults = {k: v.format(top=top) for k, v in DEFAULTS.items()}
    given = {k: str(step.options[k]) for k in KEYS if step.options.get(k)}
    if given:
        return {**defaults, **given}, "options"
    qid = next((q.id for q in step.questions_list(engine)), None)
    answer = step.answers(engine).get(qid) if qid else None
    if answer is None:
        return None, ""
    if answer_is(answer, USE_DEFAULTS, "default", "yes", "mặc định"):
        return defaults, "defaults"
    paths = parse_paths(answer)
    if not paths:
        raise StepFailed(f"{qid}: give the paths as `rtl=<filelist.f> netlist=<netlist.v> requirement=<file.md>` (or answer "
                         f"\"{USE_DEFAULTS}\")")
    return {**defaults, **paths}, "your paths"


def chosen_quiet(step, engine):
    try:
        return chosen(step, engine)
    except StepFailed:
        return None, ""


def run(step, ctx: StepContext, top: str) -> tuple[dict[str, str], str] | None:
    """(the three paths, how they were chosen), checked to exist; None while your answer is awaited."""
    project = ctx.project
    paths, how = chosen(step, ctx.engine)
    if paths is None:
        qid, answer = step.decide(ctx, "source", "ECOIN", (
            "Which inputs should the ECO use? The defaults are the asic flow's: ORG RTL `" + DEFAULTS["rtl"] + "`, ORG netlist `"
            + DEFAULTS["netlist"].format(top=top) + "`, requirement `" + DEFAULTS["requirement"] + "`. Or give your own paths."),
            [(USE_DEFAULTS, "the asic flow's RTL filelist and netlist, the requirement in eco/requirement.md"),
             (OWN_PATHS, "answer with the three paths (project-relative or absolute)")])
        if answer is None:
            step.task(ctx, "inputs", f"answer {qid}: the defaults or your paths", "waiting")
            ctx.emit("warning", message=f"ECO inputs: answer {qid} (defaults or your paths), then run again")
            return None
        paths, how = {k: v.format(top=top) for k, v in DEFAULTS.items()}, "defaults"  # (auto-answer: the first option)
    root = project.root
    req = root / paths["requirement"]
    if not req.is_file() and how != "your paths":
        req.parent.mkdir(parents=True, exist_ok=True)
        req.write_text(REQUIREMENT_STUB)
        raise StepFailed(f"write the ECO requirement in {project.rel(req)} (a template is there now), then run again")
    missing = [f"{k}: {paths[k]}" for k in KEYS if not (root / paths[k]).is_file()]
    if missing:
        raise StepFailed("ECO input not found — " + "; ".join(missing) + (" (run the asic flow first for its netlist)" if how == "defaults" else ""))
    step.task(ctx, "inputs", f"{how}: RTL {paths['rtl']}, netlist {paths['netlist']}, requirement {paths['requirement']}")
    return paths, how
