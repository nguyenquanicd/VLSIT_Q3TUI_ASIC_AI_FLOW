"""ECO step `eco_eq1`: EQ(1), the ORG netlist against the ORG RTL (Formality). The asic flow's `asic_lec` is this same check: when it passed on
the same netlist and RTL, you choose between its result and a new run; without it you choose whether to run EQ(1) at all (skipped: said in the
result, the flow goes on). Not equivalent stops the flow with the causes and what to do (`eco/reports/eq1.md`)."""
from __future__ import annotations

from pathlib import Path

from q3tui.core.project import read_json, sha256_file, sha256_json
from q3tui.flows import skill_sections
from q3tui.flows.eco.lib import eq
from q3tui.flows.eco.lib.base import EQ1_JSON, INPUTS_JSON, EcoStep, answer_is
from q3tui.pipeline.base import StepContext, StepFailed

SYSTEM = skill_sections(Path(__file__).parent / "md" / "skill.md")
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


class Step(EcoStep):
    name = "eco_eq1"
    title = "EQ(1): ORG RTL vs ORG netlist"
    deps = ("eco_inputs",)
    tool_roles = ("asic_lec",)
    hashed_options = ("message_filter", "extra_tcl")

    def inputs(self, engine) -> list[Path]:
        lec = engine.project.schemas_dir / "asic_lec.json"
        return [self.artifact(engine, INPUTS_JSON), self.org_netlist(engine), *self.org_rtl_files(engine), self._q_paths(engine)[1],
                *([lec] if lec.is_file() else [])]

    def outputs(self, engine) -> list[Path]:
        return [x for x in (self.artifact(engine, EQ1_JSON), self.reports_dir(engine) / "eq1.md") if x.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *self._q_paths(engine)]

    def missing_input(self, engine) -> str | None:
        return self.need_inputs(engine)

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        inputs = self.inputs_data(engine)
        rtl = self.org_rtl_files(engine)
        if not rtl:
            raise StepFailed(f"no RTL file in {inputs.get('rtl')}")
        self.artifact(engine, EQ1_JSON).unlink(missing_ok=True)
        # (the question is asked again when the ORG netlist or the ORG RTL changes)
        net_hash = sha256_json([sha256_file(self.org_netlist(engine)), *[sha256_file(f) for f in rtl]])[:12]
        # (asic_lec ran on the files the ref/ copies came from: they must still be what ref/ holds)
        from q3tui.flows.eco.lib.ref import pointer
        src_net = project.root / str((inputs.get("source") or {}).get("netlist") or inputs.get("netlist") or "")
        src_rtl = [project.root / k for k in (pointer(project).get("rtl_files") or {})] or rtl
        same = src_net.is_file() and sha256_file(src_net) == sha256_file(self.org_netlist(engine))
        reuse, why = lec_reuse(project, {**inputs, "netlist": project.rel(src_net) if same else inputs.get("netlist")}, src_rtl) if same \
            else (False, "the netlist asic_lec checked is not the ORG netlist in ref/ any more")
        if reuse:
            qid, answer = self.decide(ctx, f"reuse:{net_hash}", "ECOEQ", f"EQ(1): {why}. Use that result, or run EQ(1) again?",
                                     [(USE_LEC, "EQ(1) passes with asic_lec's result"), (RERUN, "Formality runs again on the ORG RTL and netlist")])
        else:
            qid, answer = self.decide(ctx, f"run:{net_hash}", "ECOEQ", f"EQ(1): {why}. Run EQ(1) (Formality: ORG RTL vs ORG netlist)?",
                                     [(RUN, "Formality checks the ORG netlist before the ECO"), (SKIP, "no check: the flow goes on, the result says skipped")])
        if answer is None:
            ctx.emit("warning", message=f"EQ(1): answer {qid}, then run again")
            return
        if reuse and answer_is(answer, USE_LEC, "use"):
            lec = read_json(project.schemas_dir / "asic_lec.json", {})
            self.write(engine, EQ1_JSON, {"status": "equivalent", "source": "asic_lec", "passing": lec.get("passing"),
                                          "report": "build/syn/asic/reports/lec.rpt", "question": qid})
            ctx.emit("log", message=f"EQ(1): passed (asic_lec's result, {lec.get('passing', '?')} compare points)")
            return
        if not reuse and answer_is(answer, SKIP, "skip", "no", "không"):
            self.write(engine, EQ1_JSON, {"status": "skipped", "source": "you", "question": qid})
            ctx.emit("warning", message=f"EQ(1) skipped ({qid}): the ORG netlist is not proven equal to the ORG RTL")
            return
        result = await eq.run_formality(self, ctx, rtl, self.org_netlist(engine), "eq1")
        self.write(engine, EQ1_JSON, {**result, "source": "formality", "question": qid})
        if result["status"] == "equivalent":
            (self.reports_dir(engine) / "eq1.md").write_text(eq.advice_md("EQ(1): ORG RTL vs ORG netlist", result, None))
            ctx.emit("log", message=f"EQ(1): equivalent ({result.get('passing', '?')} compare points)")
            return
        rep = self.reports_dir(engine)
        advice = await eq.advise(self, ctx, SYSTEM["ADVICE"],
                                 f"EQ(1): the ORG RTL (reference, filelist {inputs.get('rtl')}) against the ORG netlist {project.rel(self.org_netlist(engine))} "
                                 f"(implementation) is {result['status'].replace('_', ' ')}. Why, and what to do?",
                                 [rep / "eq1_lec.rpt", rep / "eq1_fm.log"])
        (rep / "eq1.md").write_text(eq.advice_md("EQ(1): ORG RTL vs ORG netlist — FAILED", result, advice))
        self.write(engine, EQ1_JSON, {**result, "source": "formality", "question": qid, "advice": advice.model_dump()})
        raise StepFailed(f"EQ(1): the ORG netlist is {result['status'].replace('_', ' ')} to the ORG RTL ({result.get('failing', '?')} failing "
                         f"point(s)): {advice.summary} — see eco/reports/eq1.md")
