"""Task `route` of eco_eq2: how to fix a failed EQ(2) — the recommended fix, the other step, your own words (to the step the analysis names;
`patch:` / `rtl:` first to choose), or stop. Your answer goes to that step once; the fix loop then runs it and EQ(2) again. Under auto-answer
(pipeline.auto_answer, gate mode auto_answer, --yes) the recommended fix is sent without asking."""
from __future__ import annotations

from q3tui.core.project import sha256_file
from q3tui.flows.eco.lib.base import EQ2_JSON, answer_is
from q3tui.flows.eco.lib.models import EqAdvice
from q3tui.pipeline.base import StepContext, StepFailed

TASK = ("route", "the fix to its step: your answer (ECOEQ2_), or the recommended one under auto-answer")
FIX_RTL, FIX_PATCH, OWN, STOP = "Fix RTL(F)", "Fix the patch", "My own fix", "Stop"


def route(answer: str, default: str = "eco_rtl") -> str | None:
    """Which step an answer goes to: eco_rtl, eco_patch, `default` (your own words: the step the analysis names), or None (stop)."""
    if answer_is(answer, STOP, "dừng"):
        return None
    if answer_is(answer, FIX_PATCH, "patch"):
        return "eco_patch"
    if answer_is(answer, FIX_RTL, "rtl"):
        return "eco_rtl"
    return default


def own_words(answer: str) -> str:
    """Your fix as typed (the pick-list label of "My own fix" alone says nothing)."""
    text = answer.strip()
    if answer_is(text, OWN):
        text = text[len(OWN):].lstrip(" :-").strip()
        return "" if text.startswith("<") else text
    return text


def send_answers(step, ctx: StepContext, prev: dict) -> bool:
    """Your answers to a failed EQ(2), each to its step once (then the fix loop runs it and EQ(2) again); False: none to send."""
    engine = ctx.engine
    asks = dict(prev.get("asks") or {})
    answers = step.answers(engine)
    todo = [q for q, a in asks.items() if q in answers and not a.get("sent")]
    if not todo:
        return False
    for qid in todo:
        answer, fix = answers[qid], asks[qid].get("fix") or ""
        target = route(answer, asks[qid].get("recommended") or "eco_rtl")
        picked = answer_is(answer, FIX_RTL, FIX_PATCH)
        words = "" if picked else own_words(answer)
        if target and not picked and not words:
            target = None  # ("My own fix" without the fix)
            ctx.emit("warning", message=f"EQ(2): {qid} — no fix typed; answer again with your fix, or send a change request yourself")
        asks[qid].update(sent=True, to=target)
        if target:
            text = (f"From eco_eq2 (EQ(2) failed, {qid}): " + (answer if picked else f"the user's fix: {words}")
                    + (f"\nThe analysis' fix: {fix}" if fix else "") + "\nSee eco/reports/eq2.md.")
            step.hand_back(ctx, target, text)
            ctx.emit("log", message=f"EQ(2): {qid} → {target}" + ("" if picked else " (your fix)"))
        elif answer_is(answer, STOP, "dừng"):
            ctx.emit("warning", message=f"EQ(2): {qid} — stopped by your answer; fix RTL(F) or the patch by hand and run again")
    step.write(engine, EQ2_JSON, {**prev, "asks": asks})
    step.task(ctx, "route", ", ".join(f"{q} → {asks[q].get('to') or 'nothing sent'}" for q in todo), "handed")
    return True


def run(step, ctx: StepContext, result: dict, advice: EqAdvice, rec: str, prev: dict, asks: dict) -> None:
    """The analysis' fix to `rec` under auto-answer, else the question how to fix it (ECOEQ2_)."""
    engine = ctx.engine
    rep = step.reports_dir(engine)
    auto = list(prev.get("auto") or [])  # (the fixes auto-answer sent since EQ(2) last passed)
    fix = advice.fix or advice.summary
    rtl_opt = (f"{FIX_RTL} (Recommended): {fix}" if rec == "eco_rtl" else f"{FIX_RTL} (RTL(F) does not do what the requirement asks)",
               "a change request to eco_rtl; the patch, Post NETLIST and EQ(2) follow")
    patch_opt = (f"{FIX_PATCH} (Recommended): {fix}" if rec == "eco_patch" else f"{FIX_PATCH} (the edits do not implement the RTL change)",
                 "a change request to eco_patch; Post NETLIST and EQ(2) follow")
    options = [rtl_opt, patch_opt] if rec == "eco_rtl" else [patch_opt, rtl_opt]
    options += [(f"{OWN}: <type how to fix it>", f"your words go to {rec} (start with `patch:` or `rtl:` to choose the step)"),
                (f"{STOP}: I fix it by hand", "nothing is sent; run again after your change")]
    step.write(engine, EQ2_JSON, {**result, "advice": advice.model_dump(), "asks": asks, "auto": auto})
    _meta, n = step.rounds(ctx)
    if n >= step.round_limit(ctx):
        step.reset_rounds(ctx)
        raise StepFailed(f"EQ(2) still fails after {n} round(s) of fixes: {advice.summary} — see eco/reports/eq2.md")
    if step.auto_answer(engine):  # (nobody asked: the recommended fix goes to its step)
        step.hand_back(ctx, rec, f"From eco_eq2 (EQ(2) failed, auto-answer): {options[0][0]}\nSee eco/reports/eq2.md.")
        auto.append({"round": n + 1, "to": rec, "fix": fix})
        with (rep / "eq2.md").open("a") as f:
            f.write(f"\nAuto-answer round {n + 1}: the recommended fix went to `{rec}`: {fix}\n")
        step.write(engine, EQ2_JSON, {**result, "advice": advice.model_dump(), "asks": asks, "auto": auto})
        step.task(ctx, "route", f"auto-answer: the recommended fix → {rec} (round {n + 1})", "handed")
        ctx.emit("warning", message=f"EQ(2) failed: {advice.summary[:200]} → recommended fix to {rec} (auto-answer, round {n + 1})")
        return
    qid = step.ask(engine, f"fail:{sha256_file(step.post_netlist(engine))[:12]}:{sha256_file(step.rtl_f_filelist(engine))[:8]}", "ECOEQ2_",
                   f"EQ(2) failed ({result.get('failing', '?')} failing point(s)): {advice.summary} Recommended: {fix} (→ {rec}). "
                   f"Take it, pick the other step, or type your own fix.", options)
    asks[qid] = {"owner": advice.owner, "fix": fix, "recommended": rec, "sent": False}
    step.write(engine, EQ2_JSON, {**result, "advice": advice.model_dump(), "asks": asks, "auto": auto})
    step.task(ctx, "route", f"answer {qid}", "waiting")
    ctx.emit("warning", message=f"EQ(2) failed: {advice.summary[:200]} — answer {qid} (see eco/reports/eq2.md)")
