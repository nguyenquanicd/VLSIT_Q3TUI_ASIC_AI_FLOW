"""dv step `testplan`: spec + structured spec + final config → schemas/test_plan.json (the test cases, each with the REQs it checks).

The plan of the plain SystemVerilog testbench, as a step of its own so it can be reviewed (gate: human) before the testbench is written and so a
changed plan reaches `tb` as a changed input (only the test cases that changed are rewritten). The UVM testbench (`testbench: uvm`) plans its tests in the verification contract instead.

Independence as for `tb`: the stage sees the spec, the requirements and the configuration only (deny_dirs on the RTL and the SVA).
Code: numbering and names of the test cases, unknown REQ ids dropped, conditional test cases by parameter, REQ coverage (an uncovered REQ is asked
for again, then becomes a blocking question). The LLM only plans. Changes propagate as updates: the plan is made again when a requirement, a
parameter, an answer or a change request changed, and the previous plan goes in with the list of what changed.
"""

from __future__ import annotations

from pathlib import Path

from q3tui.core.project import read_json, sha256_json, write_json
from q3tui.flows.dv.plain import plan as tb_plan
from q3tui.flows.dv.plain import task as tb_prompts
from q3tui.flows.dv.plain.plan import QuestionSweep, TbPlan, TbPlanPatch
from q3tui.flows.spec.lib import artifacts
from q3tui.flows.spec.lib.base import VlsitStep
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext, StepFailed
from q3tui.steps.common import Question, assign_question_ids, drop_settled, load_answers, render_questions, settled_block, split_feedback

PLAN = "test_plan.json"
QA_ROUNDS = 2  # the question sweep before the plan: the whole spec, then once more for what the answers opened


class PlainPlan(VlsitStep):
    name = "testplan"
    title = "Test plan"
    deps = ("config",)
    artifact = PLAN
    gate_fields = {"gate_testplan_approved": True, "gate_testplan_at": ""}

    # -- files -------------------------------------------------------------------------------------

    def inputs(self, engine) -> list[Path]:
        p = engine.project
        return [*p.spec_documents(), artifacts.path(p, "structured_spec.json"), artifacts.path(p, "final_config.json"), self._q_paths(engine)[1]]

    def outputs(self, engine) -> list[Path]:
        return [f for f in (artifacts.path(engine.project, PLAN), self._q_paths(engine)[2]) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *super().reset_files(engine)]

    def missing_input(self, engine) -> str | None:
        p = engine.project
        if not artifacts.path(p, "structured_spec.json").is_file():
            return "the parsed spec is needed first (step parse: schemas/structured_spec.json)"
        if not artifacts.path(p, "final_config.json").is_file():
            return "the configuration is needed first (step config: schemas/final_config.json)"
        return None

    # -- the stage --------------------------------------------------------------------------------------

    def _deny(self, ctx: StepContext, lay) -> list[Path]:
        p = ctx.project
        return [lay.rtl, lay.sva, p.model_dir, p.arch_dir, p.rtl_dir, p.tb_dir]  # independence: spec + requirements only

    async def _plan(self, ctx: StepContext, lay, spec: dict, params: dict, top: str | None, spec_files: list[str], answers: dict, settled: str,
                    feedback: list[str], previous: list[dict] | None, changes: list[str], uncovered: list[str], inventory: list[dict] | None = None,
                    missing_functions: dict[str, list[str]] | None = None, review: list[dict] | None = None,
                    asked: list[str] | None = None, excluded: list[dict] | None = None) -> TbPlan | TbPlanPatch:
        """The whole plan the first time (or on --regenerate); afterwards a patch: only the new, changed and removed test cases."""
        qa_done = bool((ctx.engine.state.step_meta.get(self.name, {}).get("qa") or {}).get("rounds"))
        reqs = [(r["req_id"], r.get("category", ""), r.get("text", "")) for r in spec.get("requirements", []) if r.get("req_id")]
        skills, skill_dirs = tb_prompts.quality_skills(ctx.project)
        res = await ctx.llm(Stage(
            name="tb_plan", system_prompt=tb_prompts.PLAN_SYSTEM, cwd=ctx.project.root, builtin_tools=["Read", "Grep", "Glob"],
            output_model=TbPlanPatch if previous else TbPlan, deny_dirs=self._deny(ctx, lay), add_dirs=skill_dirs, max_turns=ctx.cfg.tb.max_turns,  # (stage name `tb_plan`: the verifier role's stage family)
            prompt=tb_prompts.plan_prompt(reqs=reqs, params=params, spec_files=spec_files, top=top, previous=previous, changes=changes,
                                          answers=answers, settled=settled, feedback=feedback, uncovered=uncovered, skills=skills,
                                          inventory=inventory, missing_functions=missing_functions, review=review, asked=asked, qa_done=qa_done,
                                          excluded=excluded)))
        return res.output

    async def _sweep(self, ctx: StepContext, lay, spec: dict, params: dict, top: str | None, spec_files: list[str],
                     asked: list[tuple[str, str]], k: int) -> list[Question]:
        """The Q&A before the plan (stage `tb_plan_questions`): every point the spec leaves open, asked at once, follow-ups folded in."""
        reqs = [(r["req_id"], r.get("category", ""), r.get("text", "")) for r in spec.get("requirements", []) if r.get("req_id")]
        skills, skill_dirs = tb_prompts.quality_skills(ctx.project)
        res = await ctx.llm(Stage(
            name="tb_plan_questions" + (f"_{k + 1}" if k else ""), system_prompt=tb_prompts.QA_SYSTEM, cwd=ctx.project.root,
            builtin_tools=["Read", "Grep", "Glob"], output_model=QuestionSweep, deny_dirs=self._deny(ctx, lay), add_dirs=skill_dirs,
            max_turns=ctx.cfg.tb.max_turns,
            prompt=tb_prompts.qa_prompt(reqs=reqs, params=params, spec_files=spec_files, top=top, asked=asked, skills=skills)))
        seen = {q for q, _ in asked}
        return [q for q in (res.output.questions if res.output else []) if q.question not in seen]

    async def _qa(self, ctx: StepContext, lay, spec: dict, params: dict, top: str | None, spec_files: list[str], snapshot: dict,
                  q_json: Path, q_md: Path, answers: dict) -> bool:
        """Q&A first: before any plan, the sweep's questions; True while one of them is open (the plan waits: they are blocking, so the gate
        cannot be approved; `q3tui answer all` takes their defaults). Each answered round gets one more sweep for what the answers opened,
        up to QA_ROUNDS; a changed spec starts again."""
        engine = ctx.engine
        meta = engine.state.step_meta.setdefault(self.name, {})
        qa = meta.setdefault("qa", {})
        prev = read_json(q_json, default=[]) or []
        done = set(answers) | set(engine.state.accepted_defaults.get(self.name, {}))
        h = sha256_json(snapshot)
        if ctx.regenerate or qa.get("hash") != h:
            qa.update({"hash": h, "rounds": 0, "answered": None})
            prev = [q for q in prev if q.get("code") != "qa" or q["id"] in done]  # (a new spec: the open ones are asked again if still open)
        open_qa = [q for q in prev if q.get("code") == "qa" and q["id"] not in done]
        answered = sorted(q["id"] for q in prev if q.get("code") == "qa" and q["id"] in done)
        if not open_qa and qa["rounds"] < QA_ROUNDS and (qa["rounds"] == 0 or (answered and qa.get("answered") != answered)):
            asked = [(q["question"], answers.get(q["id"], q.get("default_assumption", ""))) for q in prev]
            ctx.emit("log", message="Q&A: reading the whole spec for open points …" if not qa["rounds"] else "Q&A: what the answers opened …")
            new = await self._sweep(ctx, lay, spec, params, top, spec_files, asked, qa["rounds"])
            qa["rounds"] += 1
            qa["answered"] = answered
            if new:
                for q in new:
                    q.blocking = True  # (Q&A first: the plan waits for an answer or the accepted default)
                ided = assign_question_ids(new, [Question.model_validate(q) for q in prev], "Q-TP")
                prev += [{**q.model_dump(), "code": "qa"} for q in ided]
                write_json(q_json, prev)
                open_qa = [q for q in prev if q.get("code") == "qa" and q["id"] not in done]
            else:
                qa["rounds"] = QA_ROUNDS  # nothing more to ask
        if not open_qa:
            return False
        qs = [Question.model_validate(q) for q in prev]
        q_md.write_text(render_questions(qs, answers, f"Open questions — {self.title}", engine.state.accepted_defaults.get(self.name, {})))
        ctx.emit("questions", count=len(open_qa), blocking=len(open_qa))
        ctx.emit("warning", message=f"Q&A first: {len(open_qa)} question(s) about the spec before the plan ({', '.join(q['id'] for q in open_qa[:8])}"
                                    f"{' …' if len(open_qa) > 8 else ''}); answer them, or `q3tui answer all` for the defaults, then run testplan again")
        return True

    async def _review_plan(self, ctx: StepContext, lay, spec: dict, spec_files: list[str], inventory: list[dict], cases: list[dict],
                           excluded: list[dict], k: int, asked: list[str] | None = None,
                           changed: set[str] | None = None) -> tuple[list[dict], list[Question]]:
        """A fresh, read-only reviewer of the plan (stage `tb_plan_review`: never the planner's session) against the tc-quality skill:
        functions the inventory misses, failure modes no legal input can show, expected values the spec does not give, depth."""
        from q3tui.flows.dv.plain.plan import TbReview

        reqs = [(r["req_id"], r.get("category", ""), r.get("text", "")) for r in spec.get("requirements", []) if r.get("req_id")]
        skills, skill_dirs = tb_prompts.quality_skills(ctx.project)
        res = await ctx.llm(Stage(
            name="tb_plan_review" + (f"_{k + 1}" if k else ""), system_prompt=tb_prompts.PLAN_REVIEW_SYSTEM, cwd=ctx.project.root,
            builtin_tools=["Read", "Grep", "Glob"], output_model=TbReview, deny_dirs=self._deny(ctx, lay), add_dirs=skill_dirs,
            max_turns=ctx.cfg.tb.max_turns,
            prompt=tb_prompts.plan_review_prompt(reqs=reqs, spec_files=spec_files, plan_path=ctx.project.rel(artifacts.path(ctx.project, PLAN)),
                                                 inventory=inventory, cases=cases, excluded=excluded, skills=skills, asked=asked, changed=changed,
                                                 qa_done=bool((ctx.engine.state.step_meta.get(self.name, {}).get("qa") or {}).get("rounds")))))
        out = res.output
        ids = changed if changed is not None else {c["tc_id"] for c in cases}
        # (an update: findings on the test cases it changed only — the reviewer kept finding new things in parts nobody touched)
        findings = [f.model_dump() for f in (out.findings if out else []) if (not f.tc_id and changed is None) or f.tc_id in ids]
        return findings, list(out.questions) if out else []

    def _changes(self, old_snap: dict | None, new: dict, old_answers: dict | None, answers: dict) -> list[str]:
        if not old_snap:
            return []
        out = []
        a, b = old_snap.get("reqs", {}), new["reqs"]
        for r in sorted(set(b) - set(a)):
            out.append(f"new requirement {r}: {b[r][2]}")
        for r in sorted(set(a) - set(b)):
            out.append(f"{r} was removed: drop it from the test cases")
        for r in sorted(set(a) & set(b)):
            if a[r] != b[r]:
                out.append(f"{r} changed: {b[r][2]} (was: {a[r][2]})")
        for k in sorted(set(old_snap.get("params", {})) | set(new["params"])):
            if old_snap.get("params", {}).get(k) != new["params"].get(k):
                out.append(f"parameter {k} = {new['params'].get(k)} (was {old_snap.get('params', {}).get(k)})")
        if (old_answers or {}) != answers:
            out.append("the user's answers changed (see below)")
        return out

    # -- run -------------------------------------------------------------------------------------------

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        lay = self.lay(engine)
        spec = artifacts.read(project, "structured_spec.json")
        config = artifacts.read(project, "final_config.json")
        if not spec or not config:
            raise StepFailed("schemas/structured_spec.json and schemas/final_config.json are needed (steps parse and config)")
        params = {k: str((v or {}).get("value")) for k, v in (config.get("parameters") or {}).items()}
        reqs = {r["req_id"]: r.get("text", "") for r in spec.get("requirements", []) if r.get("req_id")}
        meta = engine.state.step_meta.setdefault(self.name, {})
        q_json, answers_path, q_md = self._q_paths(engine)
        answers = load_answers(answers_path)
        settled = settled_block(engine.settled_questions(self.name))
        _by_unit, general = split_feedback(ctx.feedback, self.name)  # (a change request for this step is about the plan as a whole)
        top = (spec.get("metadata") or {}).get("top_module")
        if not top:
            from q3tui.flows.rtl.rtl.plan import plan_from_spec

            pl = plan_from_spec(spec)
            top = pl.top if pl else None
        spec_files = [project.rel(p) for p in project.spec_documents()]

        snapshot = {"reqs": {r["req_id"]: [r.get("category"), r.get("sva_hint"), r.get("text")] for r in spec.get("requirements", []) if r.get("req_id")},
                    "params": params, "top": top}
        if await self._qa(ctx, lay, spec, params, top, spec_files, snapshot, q_json, q_md, answers):
            ctx.unchanged = False
            return  # (Q&A first: no plan until the spec's open points are answered)
        plan_hash = sha256_json({**snapshot, "answers": answers})
        qtext = {q["id"]: q["question"] for q in read_json(q_json, default=[]) or []}
        answers_view = {(f"{k} ({qtext[k]})" if k in qtext else k): v for k, v in answers.items()}  # (the planner sees what each answer answers)
        old = meta.get("plan") or {}
        need = bool(ctx.regenerate or general or not old.get("cases") or old.get("hash") != plan_hash or not artifacts.path(project, PLAN).is_file())
        cases: list[dict] = list(old.get("cases") or [])
        excluded: list[dict] = list(old.get("excluded") or [])  # (requirements no simulation can check, each with its reason)
        asked: list[Question] = []
        warnings: list[str] = []
        wrote = False
        if need:
            changes = self._changes(old.get("snapshot"), snapshot, old.get("answers"), answers)
            inventory: list[dict] = list(old.get("inventory") or [])
            ctx.emit("log", message="planning the test cases …" if not cases else "updating the test plan …")
            if ctx.regenerate or not cases:  # (a plan made from scratch: nothing of the old one is a starting point)
                cases, excluded, inventory = [], [], []
            before = {c["tc_id"]: c for c in cases}  # (an update reviews only what it changed)

            def changed_since(base: dict[str, dict]) -> set[str]:
                return {c["tc_id"] for c in cases if base.get(c["tc_id"]) != c}

            def take(plan: TbPlan | TbPlanPatch) -> None:
                """A whole plan (the first answer) or a patch (only what changes), renumbered against the plan before. Exclusions and the inventory
                are merged: an update that did not restate them never drops them (rv32iv: REQ-043/061/078 were lost and planned again)."""
                nonlocal cases, excluded, inventory
                patch = isinstance(plan, TbPlanPatch)
                full = tb_plan.apply_patch(cases, plan.test_cases, [r.tc_id for r in plan.removed]) if patch else plan.test_cases
                norm, w = tb_plan.normalize(full, set(reqs), cases)
                warnings.extend(w)
                cases = [c.model_dump() for c in norm]
                asked.extend(q for q in plan.questions if q.question not in {a.question for a in asked})
                covered = {r for c in cases if tb_plan.applies(c, params) for r in c["req_ids"]}
                more, w_ex = tb_plan.normalize_excluded(plan.excluded, set(reqs), covered)
                warnings.extend(w_ex)
                excluded = [e for e in {e["req_id"]: e for e in [*excluded, *more]}.values() if e["req_id"] not in covered]
                new_inv = tb_plan.normalize_inventory(plan.inventory, set(reqs))
                inventory = tb_plan.merge_inventory(inventory, new_inv) if patch else (new_inv or inventory)

            def gaps() -> tuple[list[str], dict[str, list[str]]]:
                sel = [c for c in cases if tb_plan.applies(c, params)]
                ex = {e["req_id"] for e in excluded}
                return tb_plan.coverage(sel, spec, ex)["uncovered_req_ids"], tb_plan.function_gaps(sel, inventory, ex)

            take(await self._plan(ctx, lay, spec, params, top, spec_files, answers_view, settled, general, cases or None, changes, [], inventory=inventory, excluded=excluded))
            # requirements no test case covers, and inventory functions no directed test exercises: asked for again
            for _ in range(min(1, ctx.cfg.tb.max_fix_attempts)):
                unc, fgaps = gaps()
                if not (unc or fgaps):
                    break
                ctx.emit("warning", message="asking for more: " + "; ".join(
                    ([f"no test case covers {', '.join(unc)}"] if unc else [])
                    + ([f"{sum(map(len, fgaps.values()))} function(s) of the inventory have no directed test ({', '.join(list(fgaps)[:8])})"] if fgaps else [])))
                take(await self._plan(ctx, lay, spec, params, top, spec_files, answers_view, settled, general, cases, [], unc, inventory=inventory,
                                      missing_functions=fgaps, asked=[q.question for q in asked], excluded=excluded))
            # a fresh reviewer of the plan; its `must` findings go back to the planner, and the plan is reviewed again
            review: list[dict] = []
            rounds = ctx.cfg.tb.review_rounds
            update = bool(before)
            ids_now = {c["tc_id"] for c in cases}
            kept_review = [f for f in (old.get("review") or []) if f.get("tc_id") in ids_now] if update else []
            review = list(kept_review)
            todo = changed_since(before) if update else None
            for r in range(rounds + 1 if rounds > 0 else 0):
                if todo is not None and not todo:
                    break  # (an update that changed no test case: nothing new to review)
                found, qs = await self._review_plan(ctx, lay, spec, spec_files, inventory, cases, excluded, r, asked=[q.question for q in asked],
                                                    changed=todo)
                asked.extend(q for q in qs if q.question not in {a.question for a in asked})
                # the findings that stand: the new ones, and the earlier ones on test cases this review did not read again
                kept_review = ([f for f in kept_review if f.get("tc_id") not in todo] if todo is not None else []) + found
                review = kept_review
                must = [f for f in found if f.get("severity") == "must"]
                if not must or r == rounds:
                    break
                ctx.emit("warning", message=f"plan review: {len(must)} finding(s); planning again: " + "; ".join(f["problem"][:80] for f in must[:3]))
                snap = {c["tc_id"]: c for c in cases}
                take(await self._plan(ctx, lay, spec, params, top, spec_files, answers_view, settled, general, cases, [], [], inventory=inventory,
                                      missing_functions=gaps()[1], review=must, asked=[q.question for q in asked], excluded=excluded))
                if update:  # (the next review reads what the fix changed, and what its findings were about)
                    todo = {t for t in changed_since(snap) | {f["tc_id"] for f in must if f.get("tc_id")} if t in {c["tc_id"] for c in cases}}
            _unc, left = gaps()
            if left:
                warnings.append(f"{sum(map(len, left.values()))} function(s) of the inventory have no directed test: "
                                + "; ".join(f"{r}: {', '.join(fs[:6])}" for r, fs in list(left.items())[:6]))
            if review:
                warnings.append(f"plan review: {sum(f.get('severity') == 'must' for f in review)} must / {sum(f.get('severity') != 'must' for f in review)} "
                                "should finding(s) left (test_plan.json `review`)")
            meta["plan"] = {"hash": plan_hash, "snapshot": snapshot, "answers": dict(answers), "cases": cases, "excluded": excluded,
                            "inventory": inventory, "review": review, "function_gaps": left,
                            "warnings": [w for w in warnings if w.startswith(("plan review:", f"{sum(map(len, left.values()))} function(s)"))]}
            wrote = True
        selected = [c for c in cases if tb_plan.applies(c, params)]
        warnings += tb_plan.plan_warnings(selected, reqs, {e["req_id"] for e in excluded}) if wrote else []
        for w in warnings:
            ctx.emit("warning", message=w)
        for c in cases:
            if c not in selected:
                ctx.emit("log", message=f"{c['tc_id']} {c['name']}: left out — {c['conditional_param']} is {params.get(c['conditional_param'])}")
        cov = tb_plan.coverage(selected, spec, {e["req_id"] for e in excluded})
        if cov["uncovered_req_ids"]:
            ctx.emit("warning", message=f"requirements with no test case: {', '.join(cov['uncovered_req_ids'])}")
        for e in excluded:
            ctx.emit("log", message=f"{e['req_id']}: left out of simulation — {e['reason'] or 'no reason given'}")

        self._write_plan_file(ctx, spec, top, cases, excluded, params, cov, wrote)
        self._write_questions(ctx, q_json, answers_path, q_md, answers, asked, cov, wrote)
        ctx.unchanged = not wrote
        ctx.emit("log", message=f"test plan: {len(selected)}/{len(cases)} test case(s), REQ coverage {cov['coverage_pct']}%"
                                f" ({len(cov['covered_req_ids'])}/{cov['total_req_ids']}), {len(excluded)} requirement(s) left out of simulation")

    # -- outputs -----------------------------------------------------------------------------------------------------

    def _write_plan_file(self, ctx: StepContext, spec: dict, top: str | None, cases: list[dict], excluded: list[dict], params: dict, cov: dict, wrote: bool) -> None:
        engine, project = ctx.engine, ctx.project
        old = artifacts.read(project, PLAN) or {}
        md = {"ip_name": (spec.get("metadata") or {}).get("ip_name") or top or "", "gate_testplan_approved": False, "gate_testplan_at": None}
        gate = engine.state.gates.get(self.name)
        if gate and gate.status == "approved" and not wrote:
            md.update({k: v for k, v in (old.get("metadata") or {}).items() if k.startswith("gate_testplan")})  # unchanged: the approval stays
        sel = [c for c in cases if tb_plan.applies(c, params)]
        pm = engine.state.step_meta.get(self.name, {}).get("plan") or {}
        kinds = {k: sum((c.get("test_type") or "directed") == k for c in sel) for k in tb_plan.TEST_TYPES}
        artifacts.write(project, PLAN, {"metadata": md, "test_cases": [{**c, "selected": tb_plan.applies(c, params)} for c in cases], "excluded": excluded, "coverage": cov,
                                            "test_types": kinds, "warnings": tb_plan.plan_warnings(sel, {}, {e["req_id"] for e in excluded}) + pm.get("warnings", []), "params": params,
                                            "inventory": pm.get("inventory") or [], "function_gaps": pm.get("function_gaps") or {}, "review": pm.get("review") or []},
                        check=False)

    def _uncovered_question(self, cov: dict, answers: dict, q_raw: list[dict]) -> list[Question]:
        if not cov["uncovered_req_ids"]:
            return []
        prior = [q for q in q_raw if q.get("code") == "uncovered" and q["id"] in answers]
        if any(set(cov["uncovered_req_ids"]) <= set(q.get("uncovered") or []) for q in prior):
            return []  # answered before for these requirements (accepted as not simulated)
        ids = ", ".join(cov["uncovered_req_ids"])
        return [Question(id="", question=f"No test case covers {ids}. Add test cases for them, or accept that they are not checked by simulation (SVA / review only)?",
                         blocking=True, default_assumption="Accept: not checked by simulation (recorded as uncovered in test_plan.json)", kind="design_choice")]

    def _write_questions(self, ctx: StepContext, q_json: Path, answers_path: Path, q_md: Path, answers: dict, asked: list[Question], cov: dict, wrote: bool) -> None:
        engine = ctx.engine
        prev_raw = read_json(q_json, default=[]) or []
        # the LLM's questions are replaced when it planned again, kept otherwise; code questions follow the coverage now
        # (the Q&A's questions stay, answered or not; an answered question too: its text says what the answer answers)
        kept = [q for q in prev_raw if (q.get("code") is None and (not wrote or q["id"] in answers)) or q.get("code") == "qa"]
        new: list[tuple[Question, dict]] = []
        if wrote:
            fresh, dropped = drop_settled(asked, engine.settled_questions(self.name))
            new += [(q, {}) for q in fresh if q.question not in {k["question"] for k in kept}]
            if dropped:
                ctx.emit("log", message="dropped question(s) already settled: " + ", ".join(sid for _, sid in dropped))
        new += [(q, {"code": "uncovered", "uncovered": list(cov["uncovered_req_ids"])}) for q in self._uncovered_question(cov, answers, prev_raw)]
        old_code = [q for q in prev_raw if q.get("code") not in (None, "qa") and q["id"] in answers]
        ided = assign_question_ids([q for q, _ in new], [Question.model_validate(q) for q in prev_raw], "Q-TP")
        kept_ids = {q["id"] for q in kept} | {q["id"] for q in old_code}
        entries = kept + [q for q in old_code if q["id"] not in {n.id for n in ided}] + [
            {**q.model_dump(), **extra} for (_, extra), q in zip(new, ided) if q.id not in kept_ids]
        q_json.parent.mkdir(parents=True, exist_ok=True)
        write_json(q_json, entries)
        qs = [Question.model_validate(q) for q in entries]
        if qs:
            q_md.write_text(render_questions(qs, load_answers(answers_path), f"Open questions — {self.title}", engine.state.accepted_defaults.get(self.name, {})))
        open_q = [q for q in qs if q.id not in load_answers(answers_path)]
        ctx.emit("questions", count=len(open_q), blocking=sum(q.blocking for q in open_q))
