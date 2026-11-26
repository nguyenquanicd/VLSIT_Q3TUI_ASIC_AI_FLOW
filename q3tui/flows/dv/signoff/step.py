"""dv step `signoff`: how strong the plain testbench is, and what was verified (docs/spec/dv-flow.md "Sign-off").

Mutation (rule VER-11, `plain/mutation.py`): an LLM stage (`dv_mutants`; the spec, the requirements and the RTL, never the testbench: deny_dirs) proposes
`tb.mutants` requirement-matched bugs as data; code checks each (an RTL file, a `find` that occurs once), applies it to a copy of the RTL, compiles the
testbench with it (role `sim`) and runs the tests that passed (role `run`), the mutant's requirements' tests first, until one fails. Survivors go to a
fresh reviewer (`dv_mutant_review`): equivalent (left out of the score), missed (a change request to `tb` for the test case named — in spec terms, the
testbench never sees the RTL — or to `testplan` for a new one; the fix loop runs tb, simulate and this step again; a mutant is handed over once) or
unsure. The score is caught / (compiled − equivalent), overall and per requirement, against `tb.mutation_threshold`.

Updates, not re-runs: the mutants that still apply to the RTL are kept (the LLM is asked only for the ones missing), and a mutant's result is kept while
the RTL and the testbench are the same (`gen.sources_hash`). Mutation waits while a test does not pass (a failing testbench's strength means nothing).

Then code writes the verification report (`plain/report.py`) from every dv artifact. The gate is yours (human): the sign-off. The UVM testbench: N/A."""

from __future__ import annotations

import threading
from pathlib import Path

from q3tui.core.project import read_json, write_json
from q3tui.flows import skill_sections
from q3tui.flows.spec.lib import artifacts
from q3tui.flows.spec.lib.base import VlsitStep
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext, StepFailed

PROMPTS = skill_sections(Path(__file__).parent / "md" / "skill.md")
MUTATION = "dv_mutation.json"
MUTATION_MD = "dv_mutation.md"


class SignoffStep(VlsitStep):
    name = "signoff"
    title = "Sign-off"
    deps = ("simulate",)
    artifact = "dv_verification_report.json"
    gate_fields = {"gate_signoff_approved": True, "gate_signoff_at": ""}
    tool_roles = ("sim", "run")

    def _plain(self, engine) -> bool:
        from q3tui.flows.dv import uvm

        return uvm.testbench_kind(uvm.tb_options(engine)) == "plain"

    # -- files -------------------------------------------------------------------------------------

    def inputs(self, engine) -> list[Path]:
        from q3tui.flows.dv.plain import gen as tb_gen

        p, lay = engine.project, self.lay(engine)
        tb = engine.by_name.get("tb")
        sim = engine.by_name.get("simulate")
        return [*tb_gen.rtl_files(p.root, lay.rtl), *(tb.outputs(engine) if tb is not None else []),
                *(f for f in (sim.outputs(engine) if sim is not None else []) if f.name != "dv_evidence.json"),
                artifacts.path(p, "test_plan.json"), artifacts.path(p, "structured_spec.json")]

    def outputs(self, engine) -> list[Path]:
        from q3tui.flows.dv.plain import report

        lay = self.lay(engine)
        return [f for f in (lay.schemas / MUTATION, lay.schemas / report.JSON, lay.reports / MUTATION_MD, lay.reports / report.MD) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *super().reset_files(engine)]

    def missing_input(self, engine) -> str | None:
        if not self._plain(engine):
            return None
        p = engine.project
        if not artifacts.path(p, "selected_testplan.json").is_file():
            return "the testbench is not built yet (step tb: schemas/selected_testplan.json)"
        if not (self.lay(engine).schemas / "dv_test_results.json").is_file():
            return "the tests have not run yet (step simulate)"
        return None

    # -- run -------------------------------------------------------------------------------------------

    async def run(self, ctx: StepContext) -> None:
        from q3tui.flows.dv.plain import report

        lay = self.lay(ctx.engine)
        if not self._plain(ctx.engine):
            write_json(lay.schemas / MUTATION, {"status": "n/a", "note": "the UVM testbench: mutation and this report are not supported yet", "at": artifacts.now()})
            ctx.emit("log", message="signoff: the UVM testbench — mutation N/A (see reports/dv_test_results.md)")
            return
        before = read_json(lay.schemas / MUTATION, default={}) or {}
        mutation = await self._mutation(ctx, lay, before)
        kept = mutation.pop("_unchanged", False)
        write_json(lay.schemas / MUTATION, mutation)
        lay.reports.mkdir(parents=True, exist_ok=True)
        (lay.reports / MUTATION_MD).write_text(render_mutation(mutation))
        old_report = read_json(lay.schemas / report.JSON, default={}) or {}
        data = report.write(ctx.project, lay, mutation)
        same = {k: v for k, v in old_report.items() if k != "metadata"} == {k: v for k, v in data.items() if k != "metadata"}
        ctx.unchanged = same and kept and not (ctx.engine.state.step_meta.get(self.name) or {}).get("loop")
        s = data["summary"]
        ctx.emit("log", message=f"signoff: requirements {', '.join(f'{k} {v}' for k, v in s['requirements_by_status'].items())}; mutation "
                                + (f"score {s['mutation'].get('score')} ({s['mutation'].get('caught')}/{(s['mutation'].get('caught') or 0) + (s['mutation'].get('survived') or 0)})"
                                   if mutation.get("status") == "done" else str(mutation.get("status"))) + f" — {project_rel(ctx, lay.reports / report.MD)}")

    # -- mutation -------------------------------------------------------------------------------------

    async def _mutation(self, ctx: StepContext, lay, old: dict) -> dict:
        import anyio

        from q3tui.eda.tools import load_tools
        from q3tui.flows.dv.plain import gen as tb_gen
        from q3tui.flows.dv.plain import mutation as M
        from q3tui.flows.dv.plain.simulate import plan_cases

        engine, project, cfg = ctx.engine, ctx.project, ctx.cfg
        n, threshold = cfg.tb.mutants, cfg.tb.mutation_threshold
        base = {"threshold": threshold, "mutants": old.get("mutants") or [], "results": {}, "at": artifacts.now()}
        if n <= 0:
            return {**base, "status": "off", "note": "tb.mutants is 0 (Settings → TB)", "_unchanged": old.get("status") == "off"}
        cases = plan_cases(project)
        results = {t["tc_id"]: t.get("status") for t in (read_json(lay.schemas / "dv_test_results.json", default={}) or {}).get("tests") or []}
        failing = [c["tc_id"] for c in cases if results.get(c["tc_id"]) not in ("PASS", "BLOCKED")]
        passing = [c for c in cases if results.get(c["tc_id"]) == "PASS"]
        if failing or not passing:
            note = (f"{len(failing)} test(s) do not pass ({', '.join(failing[:8])}{' …' if len(failing) > 8 else ''}): the strength of a failing testbench is not measured"
                    if failing else "no test passed")
            ctx.emit("warning", message=f"signoff: mutation waits — {note}")
            return {**base, "status": "not_run", "note": note}
        rtl = tb_gen.rtl_files(project.root, lay.rtl)
        if not rtl:
            return {**base, "status": "not_run", "note": "no RTL (src/rtl)"}
        tools = load_tools(cfg, project.root)
        sources = tb_gen.sources_hash(project.root, lay.tb, lay.rtl)
        spec = artifacts.read(project, "structured_spec.json") or {}
        reqs = {r["req_id"]: r.get("text", "") for r in spec.get("requirements") or [] if r.get("req_id")}

        # 1. the mutants: the ones that still apply are kept, the LLM writes the ones missing -----------------------------------------
        keep = [] if ctx.regenerate else M.still_valid(old.get("mutants") or [], project.root, rtl)[:n]
        rejected: list[dict] = []
        llm = 0
        for attempt in range(1 + max(1, cfg.tb.max_fix_attempts)):
            need = n - len(keep)
            if need <= 0:
                break
            plan = await ctx.llm(self._mutant_stage(ctx, lay, reqs, rtl, keep, rejected, need))
            llm += 1
            ok, bad = M.normalize(plan.output.mutants if plan.output else [], set(reqs), keep, project.root, rtl)
            keep += ok[:need]
            rejected = bad if len(ok) < need else []  # (enough valid ones: the others are not needed)
            if rejected:
                ctx.emit("warning", message=f"signoff: {len(bad)} mutant(s) could not be applied, asking again: "
                                            + "; ".join(f"{b.get('file')}: {b['problem']}" for b in bad[:4]))
            else:
                break

        # 2. the runs: a result is kept while the sources and the edit are the same -------------------------------------------------------
        reuse = {M.key(m): (old.get("results") or {}).get(m["id"]) for m in old.get("mutants") or []} if old.get("sources") == sources else {}
        res: dict[str, dict] = {}
        todo = []
        for m in keep:
            r = reuse.get(M.key(m))
            if r and r.get("status") in ("caught", "survived", "not_compiled"):
                res[m["id"]] = r
            else:
                todo.append(m)
        if todo:
            ctx.emit("log", message=f"signoff: running {len(todo)} mutant(s) ({len(passing)} passing test(s), {cfg.tb.sim_jobs()} at once) …")
        limiter = anyio.CapacityLimiter(cfg.tb.sim_jobs())
        abort = threading.Event()

        async def one(m: dict) -> None:
            async with limiter:
                r = await anyio.to_thread.run_sync(lambda: M.run_mutant(tools, project, lay, m, passing, rtl, stop=abort))
            res[m["id"]] = r
            ctx.emit("log", message=f"mutant {m['id']} ({', '.join(m.get('req_ids') or []) or '–'}): {r['status']}"
                                    + (f" by {r['by']}" if r.get("by") else "") + f" [{len(res)}/{len(keep)}]")
        try:
            async with anyio.create_task_group() as tg:
                for m in todo:
                    tg.start_soon(one, m)
        except BaseException:
            abort.set()  # (cancelled: the running simulators are killed)
            raise
        errors = [m["id"] for m in keep if res.get(m["id"], {}).get("status") == "error"]
        if errors and len(errors) == len(keep):
            raise StepFailed(f"signoff: the tools failed on every mutant: {res[errors[0]].get('note')}")

        # 3. the survivors: equivalent, or a bug the testbench misses (handed back) ------------------------------------------------------
        old_verdicts = {M.key(m): (old.get("survivors") or {}).get(m["id"]) for m in old.get("mutants") or []} if old.get("sources") == sources else {}
        survivors = [m for m in keep if res.get(m["id"], {}).get("status") == "survived"]
        verdicts: dict[str, dict] = {}
        fresh = []
        for m in survivors:
            v = old_verdicts.get(M.key(m))
            if v:
                verdicts[m["id"]] = v
            else:
                fresh.append(m)
        if fresh:
            out = await ctx.llm(self._survivor_stage(ctx, lay, reqs, fresh))
            llm += 1
            ids = {m["id"] for m in fresh}
            for v in (out.output.verdicts if out.output else []):
                if v.mutant_id in ids:
                    verdicts[v.mutant_id] = v.model_dump()
        equivalent = sorted(i for i, v in verdicts.items() if v.get("verdict") == "equivalent")
        self._hand_back(ctx, [m for m in survivors if (verdicts.get(m["id"]) or {}).get("verdict") == "missed"], verdicts, cases)

        score = M.score(keep, res, set(equivalent), threshold)
        below = [r for r, c in score["per_req"].items() if c["status"] == "below"]
        if score["score"] is not None and score["score"] < threshold:
            ctx.emit("warning", message=f"signoff: mutation score {score['score']} is below {threshold} ({score['caught']} of "
                                        f"{score['compiled'] - score['equivalent']} bugs caught)")
        if below:
            ctx.emit("warning", message=f"signoff: {len(below)} requirement(s) below the mutation threshold: {', '.join(below[:10])}")
        data = {**base, "status": "done", "sources": sources, "mutants": keep, "rejected": rejected, "results": res, "survivors": verdicts,
                "equivalent": equivalent, "score": score}
        same = {k: v for k, v in data.items() if k != "at"} == {k: v for k, v in old.items() if k != "at"}
        data["_unchanged"] = same and not todo and not llm
        return data

    def _hand_back(self, ctx: StepContext, missed: list[dict], verdicts: dict[str, dict], cases: list[dict]) -> None:
        """A bug no test catches is a missing check or stimulus (VER-11): back to the testbench, once per mutant, in spec terms."""
        from q3tui.flows.dv.plain import mutation as M
        from q3tui.steps.common import scoped

        engine, cfg = ctx.engine, ctx.cfg
        meta = engine.state.step_meta.setdefault(self.name, {})
        if not missed or not cfg.tb.mutation_hand_back:
            meta["rounds"] = 0  # (nothing to hand back: the rounds start afresh)
            return
        handed = set(meta.get("handed") or [])
        rounds = int(meta.get("rounds") or 0)
        ids = {c["tc_id"] for c in cases}
        sent, again = [], []
        for m in missed:
            v = verdicts[m["id"]]
            if M.key(m) in handed:
                again.append(m["id"])
                continue
            if rounds >= cfg.pipeline.max_fix_iterations:
                break
            text = (f"From mutation testing ({m['id']}, {', '.join(m.get('req_ids') or []) or 'no REQ'}): a bug that breaks this passed every test — "
                    f"{m.get('description', '')}. {v.get('request', '')}").strip()
            named = (v.get("tc_id") or "").strip()
            tc = named if named in ids else ""
            if named and not tc:  # (an id that is not a selected test case: the one that checks most of the mutant's requirements)
                mine = set(m.get("req_ids") or [])
                best = max(cases, key=lambda c: len(set(c.get("req_ids") or []) & mine), default=None)
                tc = best["tc_id"] if best is not None and set(best.get("req_ids") or []) & mine else ""
            # (no test case named: a new one is needed — the plan's to add)
            if tc:
                engine.request_change("tb", scoped("tb", tc, text))
            else:
                engine.request_change("testplan", text + " Add a test case for it.")
            handed.add(M.key(m))
            sent.append(f"{m['id']} → {tc or 'testplan'}")
        meta = engine.state.step_meta.setdefault(self.name, {})
        meta["handed"] = sorted(handed)
        if again:
            ctx.emit("warning", message=f"signoff: {', '.join(again)} still not caught after the testbench was changed for it (handed over once; see the report)")
        if sent:
            meta["loop"], meta["rounds"] = True, rounds + 1
            ctx.emit("log", message=f"signoff: {len(sent)} missed bug(s) handed back: {', '.join(sent)}; tb, simulate and signoff run again")

    # -- stages ------------------------------------------------------------------------------------------

    def _skills(self, project):
        from q3tui.flows.dv.plain.task import DV_FLOW_FILE
        from q3tui.flows.rtl.lib import skills as skillmod

        found = skillmod.discover(project.config_dir, DV_FLOW_FILE, ["bug-injection"])
        return skillmod.index(found, project.root), skillmod.add_dirs(found)

    def _mutant_stage(self, ctx: StepContext, lay, reqs: dict[str, str], rtl: list[Path], keep: list[dict], rejected: list[dict], need: int) -> Stage:
        from q3tui.flows.dv.plain.mutation import MutantPlan
        from q3tui.steps.common import spec_block

        project = ctx.project
        skills, dirs = self._skills(project)
        block, _ = spec_block(project)
        parts = [f"# Task: propose {need} mutant(s) (bugs) for the RTL below", "", "## Specification", block, "",
                 "## Requirements", "\n".join(f"- {k}: {v}" for k, v in reqs.items()) or "(none)", "",
                 "## RTL files (read them; `file` is one of these)", "\n".join(f"- {project.rel(p)}" for p in rtl), ""]
        if keep:
            parts += ["## Mutants already kept (do not repeat them; give the requirements without one first)",
                      "\n".join(f"- {m['id']} {m['file']} [{', '.join(m.get('req_ids') or [])}]: {m.get('description', '')}" for m in keep), ""]
        if rejected:
            parts += ["## Rejected in the last answer (fix or replace them)", "\n".join(f"- {m.get('file')}: {m['problem']}" for m in rejected[:20]), ""]
        parts += [skills, "", f"Return `mutants`: {need} of them."]
        return Stage(name="dv_mutants", system_prompt=PROMPTS["MUTANTS_SYSTEM"], prompt="\n".join(parts), cwd=project.root,
                     builtin_tools=["Read", "Grep", "Glob"], output_model=MutantPlan, add_dirs=dirs,
                     deny_dirs=[project.tb_dir, lay.tb, lay.sva, lay.sim, project.model_dir], max_turns=ctx.cfg.tb.max_turns)

    def _survivor_stage(self, ctx: StepContext, lay, reqs: dict[str, str], survivors: list[dict]) -> Stage:
        from q3tui.flows.dv.plain.mutation import SurvivorReview
        from q3tui.steps.common import spec_block

        project = ctx.project
        skills, dirs = self._skills(project)
        block, _ = spec_block(project)
        tests = artifacts.read(project, "selected_testplan.json") or {}
        parts = ["# Task: review the mutants every test passed", "", "## Specification", block, "",
                 "## Requirements", "\n".join(f"- {k}: {v}" for k, v in reqs.items()) or "(none)", "",
                 f"## Testbench: {project.rel(lay.tb)}/ (tb_top.sv, tests/); the test cases", "\n".join(
                     f"- {c['tc_id']} {c.get('name', '')} [{', '.join(c.get('req_ids') or [])}]: {c.get('description', '')}"
                     for c in tests.get("test_cases") or [] if c.get("selected")), "", "## The surviving mutants"]
        for m in survivors:
            parts += [f"### {m['id']} [{', '.join(m.get('req_ids') or [])}] {m.get('kind', '')}: {m.get('description', '')}", f"file `{m['file']}`:",
                      "```diff", *[f"- {ln}" for ln in m["find"].splitlines()], *[f"+ {ln}" for ln in m["replace"].splitlines()], "```", ""]
        parts += [skills, "", "Return one verdict per mutant."]
        return Stage(name="dv_mutant_review", system_prompt=PROMPTS["SURVIVORS_SYSTEM"], prompt="\n".join(parts), cwd=project.root,
                     builtin_tools=["Read", "Grep", "Glob"], output_model=SurvivorReview, add_dirs=dirs,
                     deny_dirs=[lay.sva, lay.sim, project.model_dir], max_turns=ctx.cfg.tb.max_turns)


def project_rel(ctx: StepContext, p: Path) -> str:
    return ctx.project.rel(p)


def render_mutation(d: dict) -> str:
    out = ["# Mutation testing (VER-11)", "", f"Status: **{d.get('status')}**" + (f" — {d['note']}" if d.get("note") else ""), ""]
    if d.get("status") != "done":
        return "\n".join(out) + "\n"
    s = d["score"]
    out += [f"Score {s['score']} (threshold {s['threshold']}): {s['caught']} caught, {s['survived']} survived, {s['equivalent']} equivalent, "
            f"{s['mutants'] - s['compiled']} not compiled (not counted), of {s['mutants']}. Bugs are injected into a copy of the RTL (`build/sim/mutate/`), never `src/rtl`.", "",
            "| Mutant | REQs | Kind | Bug | File | Result | Caught by | Check / review |", "|---|---|---|---|---|---|---|---|"]
    for m in d["mutants"]:
        r = d["results"].get(m["id"]) or {}
        v = (d.get("survivors") or {}).get(m["id"]) or {}
        tail = r.get("check") or (f"{v.get('verdict')} (AI review, advisory): {v.get('reason', '')}" if v else r.get("note", ""))
        cell = lambda x: str(x or "–").replace("|", "\\|").replace("\n", " ")[:220]  # noqa: E731
        out.append(f"| {m['id']} | {cell(', '.join(m.get('req_ids') or []))} | {cell(m.get('kind'))} | {cell(m.get('description'))} | `{m['file']}` | "
                   f"{r.get('status', '–')} | {cell(r.get('by'))} | {cell(tail)} |")
    if d.get("rejected"):
        out += ["", "Rejected (could not be applied): " + "; ".join(f"{m.get('file')}: {m['problem']}" for m in d["rejected"])]
    return "\n".join(out) + "\n"
