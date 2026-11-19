"""Task `decide` of eco_eq1: the asic flow's `asic_lec` is this same check — when it passed on the same netlist and RTL, you choose between its
result and a new run; without it you choose whether to run EQ(1) at all. The question is asked again when the ORG netlist or RTL changes."""
from __future__ import annotations

from pathlib import Path

from q3tui.core.project import read_json, sha256_file, sha256_json
from q3tui.pipeline.base import StepContext

TASK = ("decide", "use the asic flow's LEC result, run Formality, or skip (ECOEQ)")
USE_LEC, RERUN = "Use the asic_lec result", "Run EQ(1) again"
RUN, SKIP = "Run EQ(1)", "Skip EQ(1)"


def lec_reuse(project, inputs: dict, rtl_files: list[Path]) -> tuple[bool, str]:
    """(asic_lec's result stands for EQ(1), why / why not): it passed, on the ORG netlist, after the netlist and the RTL last changed."""
    lec_json = project.schemas_dir / "asic_lec.json"
    lec = read_json(lec_json, None)
    if not lec:
        return False, "the asic flow's equivalence check (asic_lec) has not run"
    if lec.get("status") != "equivalent":
        return False, f"asic_lec did not pass ({lec.get('status', '?')})"
    net = project.root / str(inputs.get("netlist") or "")
    if (project.root / str(lec.get("netlist") or "")).resolve() != net.resolve():
        return False, f"asic_lec checked another netlist ({lec.get('netlist')})"
    newest = max([p.stat().st_mtime for p in [net, *rtl_files] if p.is_file()], default=0.0)
    if lec_json.stat().st_mtime < newest:
        return False, "the netlist or the RTL changed after asic_lec ran"
    return True, f"asic_lec passed on {lec.get('netlist')} ({lec.get('passing', '?')} compare points)"


def run(step, ctx: StepContext, inputs: dict, rtl: list[Path]) -> tuple[str, str, bool] | None:
    """(the question id, your answer, asic_lec's result can stand for EQ(1)), or None while the answer is awaited."""
    engine, project = ctx.engine, ctx.project
    # (the question is asked again when the ORG netlist or the ORG RTL changes)
    net_hash = sha256_json([sha256_file(step.org_netlist(engine)), *[sha256_file(f) for f in rtl]])[:12]
    # (asic_lec ran on the files the ref/ copies came from: they must still be what ref/ holds)
    from q3tui.flows.eco.lib.ref import pointer
    src_net = project.root / str((inputs.get("source") or {}).get("netlist") or inputs.get("netlist") or "")
    src_rtl = [project.root / k for k in (pointer(project).get("rtl_files") or {})] or rtl
    same = src_net.is_file() and sha256_file(src_net) == sha256_file(step.org_netlist(engine))
    reuse, why = lec_reuse(project, {**inputs, "netlist": project.rel(src_net) if same else inputs.get("netlist")}, src_rtl) if same \
        else (False, "the netlist asic_lec checked is not the ORG netlist in ref/ any more")
    if reuse:
        qid, answer = step.decide(ctx, f"reuse:{net_hash}", "ECOEQ", f"EQ(1): {why}. Use that result, or run EQ(1) again?",
                                  [(USE_LEC, "EQ(1) passes with asic_lec's result"), (RERUN, "Formality runs again on the ORG RTL and netlist")])
    else:
        qid, answer = step.decide(ctx, f"run:{net_hash}", "ECOEQ", f"EQ(1): {why}. Run EQ(1) (Formality: ORG RTL vs ORG netlist)?",
                                  [(RUN, "Formality checks the ORG netlist before the ECO"), (SKIP, "no check: the flow goes on, the result says skipped")])
    if answer is None:
        step.task(ctx, "decide", f"answer {qid}", "waiting")
        ctx.emit("warning", message=f"EQ(1): answer {qid}, then run again")
        return None
    step.task(ctx, "decide", f"{qid}: {answer}")
    return qid, answer, reuse
