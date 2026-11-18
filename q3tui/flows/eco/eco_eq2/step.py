"""ECO step `eco_eq2`: EQ(2), the Post NETLIST against RTL(F) (Formality). Not equivalent: an LLM reads the report with the RTL change and the
patch (`eco/reports/eq2.md`: causes, who owns the fix, the recommended fix) and you are asked how to fix it: the recommended fix, the other step,
your own words (to the step the analysis names; `patch:` / `rtl:` first to choose), or stop. Your answer goes to that step once; the fix loop
then runs it and EQ(2) again. Under auto-answer (pipeline.auto_answer, gate mode auto_answer, --yes) the recommended fix is sent without asking."""
from __future__ import annotations

from pathlib import Path

from q3tui.core.project import sha256_file
from q3tui.flows import skill_sections
from q3tui.flows.eco.lib import eq
from q3tui.flows.eco.lib.base import APPLY_JSON, EQ2_JSON, EcoStep, answer_is
from q3tui.pipeline.base import StepContext, StepFailed

SYSTEM = skill_sections(Path(__file__).parent / "md" / "skill.md")
FIX_RTL, FIX_PATCH, OWN, STOP = "Fix RTL(F)", "Fix the patch", "My own fix", "Stop"
STEP_OF = {"rtl": "eco_rtl"}  # the analysis' owner -> the step that fixes it (patch, netlist, setup, unclear: the patch)


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


class Step(EcoStep):
    name = "eco_eq2"
    title = "EQ(2): RTL(F) vs Post NETLIST"
    deps = ("eco_apply",)
    tool_roles = ("asic_lec",)
    hashed_options = ("message_filter", "extra_tcl")

    def inputs(self, engine) -> list[Path]:
        return [self.rtl_f_filelist(engine), *self.rtl_f_files(engine), self.post_netlist(engine), self._q_paths(engine)[1]]

    def outputs(self, engine) -> list[Path]:
        return [f for f in (self.artifact(engine, EQ2_JSON), self.reports_dir(engine) / "eq2.md") if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *self._q_paths(engine)]

    def missing_input(self, engine) -> str | None:
        if not self.post_netlist(engine).is_file() or (self.read(engine, APPLY_JSON, {}) or {}).get("status") != "pass":
            return "the Post NETLIST is needed first (step eco_apply)"
        return None

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        prev = self.read(engine, EQ2_JSON, {}) or {}
        asks = dict(prev.get("asks") or {})
        answers = self.answers(engine)
        todo = [q for q, a in asks.items() if q in answers and not a.get("sent")]
        if todo:  # your answer to a failed EQ(2): it goes to its step once, then the fix loop runs it and EQ(2) again
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
                    self.hand_back(ctx, target, text)
                    ctx.emit("log", message=f"EQ(2): {qid} → {target}" + ("" if picked else " (your fix)"))
                elif answer_is(answer, STOP, "dừng"):
                    ctx.emit("warning", message=f"EQ(2): {qid} — stopped by your answer; fix RTL(F) or the patch by hand and run again")
            self.write(engine, EQ2_JSON, {**prev, "asks": asks})
            return
        result = await eq.run_formality(self, ctx, self.rtl_f_files(engine), self.post_netlist(engine), "eq2")
        rep = self.reports_dir(engine)
        if result["status"] == "equivalent":
            (rep / "eq2.md").write_text(eq.advice_md("EQ(2): RTL(F) vs Post NETLIST", result, None))
            self.write(engine, EQ2_JSON, {**result, "asks": asks})
            ctx.emit("log", message=f"EQ(2): equivalent ({result.get('passing', '?')} compare points)")
            self.reset_rounds(ctx)
            return
        advice = await eq.advise(self, ctx, SYSTEM["ADVICE"],
                                 f"EQ(2): RTL(F) (reference, {project.rel(self.rtl_f_filelist(engine))}) against the Post NETLIST "
                                 f"{project.rel(self.post_netlist(engine))} (the ORG netlist {project.rel(self.org_netlist(engine))} with the patch "
                                 f"{project.rel(self.patch_file(engine))}) is {result['status'].replace('_', ' ')}. Why, and who fixes it?",
                                 [rep / "eq2_lec.rpt", rep / "eq2_fm.log", self.rtl_diff(engine), self.patch_file(engine)])
        auto = list(prev.get("auto") or [])  # (the fixes auto-answer sent since EQ(2) last passed)
        (rep / "eq2.md").write_text(eq.advice_md("EQ(2): RTL(F) vs Post NETLIST — FAILED", result, advice)
                                    + "".join(f"\nAuto-answer round {a['round']}: the recommended fix went to `{a['to']}`: {a['fix']}\n" for a in auto))
        fix = advice.fix or advice.summary
        rec = STEP_OF.get(advice.owner, "eco_patch")
        rtl_opt = (f"{FIX_RTL} (Recommended): {fix}" if rec == "eco_rtl" else f"{FIX_RTL} (RTL(F) does not do what the requirement asks)",
                   "a change request to eco_rtl; the patch, Post NETLIST and EQ(2) follow")
        patch_opt = (f"{FIX_PATCH} (Recommended): {fix}" if rec == "eco_patch" else f"{FIX_PATCH} (the edits do not implement the RTL change)",
                     "a change request to eco_patch; Post NETLIST and EQ(2) follow")
        options = [rtl_opt, patch_opt] if rec == "eco_rtl" else [patch_opt, rtl_opt]
        options += [(f"{OWN}: <type how to fix it>", f"your words go to {rec} (start with `patch:` or `rtl:` to choose the step)"),
                    (f"{STOP}: I fix it by hand", "nothing is sent; run again after your change")]
        self.write(engine, EQ2_JSON, {**result, "advice": advice.model_dump(), "asks": asks, "auto": auto})
        _meta, n = self.rounds(ctx)
        if n >= self.round_limit(ctx):
            self.reset_rounds(ctx)
            raise StepFailed(f"EQ(2) still fails after {n} round(s) of fixes: {advice.summary} — see eco/reports/eq2.md")
        if self.auto_answer(engine):  # (nobody asked: the recommended fix goes to its step)
            self.hand_back(ctx, rec, f"From eco_eq2 (EQ(2) failed, auto-answer): {options[0][0]}\nSee eco/reports/eq2.md.")
            auto.append({"round": n + 1, "to": rec, "fix": fix})
            with (rep / "eq2.md").open("a") as f:
                f.write(f"\nAuto-answer round {n + 1}: the recommended fix went to `{rec}`: {fix}\n")
            self.write(engine, EQ2_JSON, {**result, "advice": advice.model_dump(), "asks": asks, "auto": auto})
            ctx.emit("warning", message=f"EQ(2) failed: {advice.summary[:200]} → recommended fix to {rec} (auto-answer, round {n + 1})")
            return
        qid = self.ask(engine, f"fail:{sha256_file(self.post_netlist(engine))[:12]}:{sha256_file(self.rtl_f_filelist(engine))[:8]}", "ECOEQ2_",
                       f"EQ(2) failed ({result.get('failing', '?')} failing point(s)): {advice.summary} Recommended: {fix} (→ {rec}). "
                       f"Take it, pick the other step, or type your own fix.", options)
        asks[qid] = {"owner": advice.owner, "fix": fix, "recommended": rec, "sent": False}
        self.write(engine, EQ2_JSON, {**result, "advice": advice.model_dump(), "asks": asks, "auto": auto})
        ctx.emit("warning", message=f"EQ(2) failed: {advice.summary[:200]} — answer {qid} (see eco/reports/eq2.md)")
