"""Shared pieces of the ECO flow's steps: the inputs (ORG RTL, ORG netlist, requirement: chosen by `eco_inputs`), where RTL(F), the patch, the
Post NETLIST, the reports and the results go, the questions, the tool runs and the fix-loop bound."""
from __future__ import annotations

from pathlib import Path

import anyio

from q3tui.core.project import read_json, sha256_json
from q3tui.flows.asic.lib.base import AsicStep
from q3tui.pipeline.base import StepFailed
from q3tui.steps.common import Question, QuestionOption, assign_question_ids, load_answers, StepQuestions

INPUTS_JSON = "eco_inputs.json"  # schemas/: the inputs as chosen (paths, hashes, top)
EQ1_JSON = "eco_eq1.json"
RTL_JSON = "eco_rtl.json"
PATCH_JSON = "eco_patch.json"
APPLY_JSON = "eco_apply.json"
EQ2_JSON = "eco_eq2.json"
STA_JSON = "eco_sta.json"
SPEC_JSON = "eco_spec.json"
VERIFY_JSON = "eco_verify.json"
TASKS_JSON = "eco_tasks.json"  # schemas/: {step: {task: {status, note}}}: what the tasks of each step did in its last run
CONCERN_KEEP, CONCERN_OWN = "Keep the change", "My answer"  # (the options of a concern question: ask_concerns)

# the inputs when you take the defaults: what the asic flow leaves (`{top}`: the top module)
DEFAULTS = {"rtl": "src/rtl/filelist.f", "netlist": "build/syn/asic/netlist/{top}.v", "requirement": "eco/requirement.md"}


def task_prompt(task_file: str) -> str:
    """The prompt of a task: `<step>/tasks/<task>.md` beside its code `<task>.py` (workflow `flows/eco/` → step `<step>/` → task)."""
    return Path(task_file).with_suffix(".md").read_text().strip()


class EcoStep(StepQuestions, AsicStep):
    """Base of the ECO flow's steps (the library / tool / artifact helpers are the ASIC flow's).
    Files are copied with shutil.copyfile, not copy2: in a project shared by several users, copying the mode / mtime onto a file
    another user owns fails (EPERM) although its content can be written."""

    # -- where things are ------------------------------------------------------------------------------------------
    def eco_dir(self, engine) -> Path:
        return engine.project.root / "eco"

    def reports_dir(self, engine) -> Path:
        return self.eco_dir(engine) / "reports"

    def build_dir(self, engine) -> Path:
        d = engine.project.build_dir / "eco" / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def workdir(self, engine) -> Path:
        d = engine.project.state_dir / "eco" / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def inputs_data(self, engine) -> dict:
        return read_json(engine.project.schemas_dir / INPUTS_JSON, {}) or {}

    def top(self, engine) -> str | None:
        return (self.options.get("top") or self.inputs_data(engine).get("top") or self._inputs_step_option(engine, "top")
                or AsicStep.top(self, engine))

    def _inputs_step_option(self, engine, key: str):
        step = next((s for s in engine.steps if s.kind == "eco.eco_inputs"), None)
        return (step.options if step else {}).get(key)

    def libraries(self, engine) -> list[str]:
        """The `.db` libraries: `library` of the eco_inputs step (one setting for the flow), else this step's own, else the library the
        asic flow synthesized the ORG netlist with (`schemas/asic_synth.json` of the ref, then of the project)."""
        import os
        raw = self._inputs_step_option(engine, "library") or self.options.get("library")
        if not raw:
            ref = self.ref_dir(engine)
            for d in ([ref / "schemas"] if ref else []) + [engine.project.schemas_dir]:
                raw = (read_json(d / "asic_synth.json", {}) or {}).get("library")
                if raw:
                    break
        items = [raw] if isinstance(raw, str) else list(raw or [])
        return [str(Path(os.path.expandvars(str(x))).expanduser()) for x in items if str(x).strip()]

    def org_filelist(self, engine) -> Path | None:
        p = self.inputs_data(engine).get("rtl")
        return engine.project.root / p if p else None

    def org_rtl_files(self, engine) -> list[Path]:
        fl = self.org_filelist(engine)
        if not fl or not fl.is_file():
            return []
        from q3tui.hdl.filelist import parse_filelist
        return parse_filelist(fl, engine.project.root).files

    def mode(self, engine) -> str:
        """`project` (the ECO modifies this project's spec and RTL in place) or `external` (a fire-fighting ECO on RTL from elsewhere)."""
        return self.inputs_data(engine).get("mode") or "external"

    def ref_dir(self, engine) -> Path | None:
        """ref/<name>/: the ORG design the ECO started from (eco_inputs: lib/ref.py)."""
        p = self.inputs_data(engine).get("ref")
        return engine.project.root / p if p else None

    def org_dir(self, engine) -> Path:
        ref = self.ref_dir(engine)
        return ref / "netlist" if ref else self.eco_dir(engine) / "org"

    def org_netlist(self, engine) -> Path:
        return self.org_dir(engine) / f"{self.top(engine)}.v"

    def org_sdc(self, engine) -> Path:
        return self.org_dir(engine) / f"{self.top(engine)}.sdc"

    def org_svf(self, engine) -> Path:
        """The SVF of the ORG synthesis (copied from beside the netlist): Formality's guidance for EQ(1) and EQ(2)."""
        return self.org_dir(engine) / f"{self.top(engine)}.svf"

    def requirement(self, engine) -> Path | None:
        p = self.inputs_data(engine).get("requirement")
        return engine.project.root / p if p else None

    def rtl_f_dir(self, engine) -> Path:
        """Where RTL(F) is: the project's RTL itself (project mode: the ECO modifies the design), else a copy in eco/rtl/."""
        return engine.project.rtl_dir if self.mode(engine) == "project" else self.eco_dir(engine) / "rtl"

    def rtl_f_filelist(self, engine) -> Path:
        src = (self.inputs_data(engine).get("source") or {}).get("rtl")
        if self.mode(engine) == "project" and src:
            return engine.project.root / src
        return self.rtl_f_dir(engine) / "filelist.f"

    def spec_diff(self, engine) -> Path:
        return self.eco_dir(engine) / "spec.diff"

    def rtl_f_files(self, engine) -> list[Path]:
        fl = self.rtl_f_filelist(engine)
        if not fl.is_file():
            return []
        from q3tui.hdl.filelist import parse_filelist
        return parse_filelist(fl, engine.project.root).files

    def rtl_diff(self, engine) -> Path:
        return self.eco_dir(engine) / "rtl.diff"

    def patch_dir(self, engine) -> Path:
        return self.eco_dir(engine) / "patch"

    def patch_file(self, engine) -> Path:
        return self.patch_dir(engine) / "eco_patch.tcl"

    def sta_fixes(self, engine) -> list[Path]:
        d = self.patch_dir(engine)
        return sorted(d.glob("sta_fix_*.tcl"), key=lambda p: int(p.stem.rsplit("_", 1)[-1])) if d.is_dir() else []

    def post_netlist(self, engine) -> Path:
        return self.eco_dir(engine) / "netlist" / f"{self.top(engine)}.v"

    # -- checks -----------------------------------------------------------------------------------------------------
    def need_inputs(self, engine) -> str | None:
        if not self.inputs_data(engine):
            return "the inputs are needed first (step eco_inputs)"
        if not self.top(engine):
            return "no top module (eco_inputs: options.top)"
        return None

    def asic_view(self, engine, files: list[Path]) -> list[Path]:
        """RTL files as the synthesis read them: a memory wrapper the asic flow implemented with macros (`asic_macro`) replaced by its
        ASIC body, whether it is the project's file (src/rtl/…) or its ORG copy in ref/<name>/ (the netlist has the macros, so an
        equivalence check against the behavioural wrapper cannot pass). shortcut: an ECO that edits a memory wrapper itself is not seen
        by EQ (the ASIC body stands for it); such an ECO needs asic_macro to run again first."""
        root = engine.project.root
        impl = {w["file"]: root / w["asic_file"] for w in (self.macros(engine).get("wrappers") or {}).values()
                if w.get("file") and w.get("asic_file") and (root / w["asic_file"]).is_file()}
        if not impl:
            return files
        ref = self.ref_dir(engine)
        prefix = f"{engine.project.rel(ref)}/" if ref else None

        def key(f: Path) -> str:
            rel = engine.project.rel(f)
            return rel[len(prefix):] if prefix and rel.startswith(prefix) else rel

        return [impl.get(key(f), f) for f in files]

    def need_libraries(self, engine) -> list[str]:
        # (+ the .db of the memory macros asic_macro compiled: the netlist instantiates them)
        libs = list(dict.fromkeys([*self.libraries(engine), *self.macro_dbs(engine)]))
        if not libs:
            raise StepFailed("no library: set `library` (the .db of the standard cells) of eco_inputs (Settings, or q3tui.yaml step_options); "
                             "no schemas/asic_synth.json gives it")
        missing = [x for x in libs if not Path(x).is_file()]
        if missing:
            raise StepFailed(f"library not found: {', '.join(missing)}")
        return libs

    async def need_tool(self, engine, role: str, hint: str):
        from q3tui.eda import tools as toolmod
        from q3tui.eda.base import ToolUnavailable
        try:
            tools = self.tools(engine)
            if not await anyio.to_thread.run_sync(lambda: toolmod.available(tools, role)):
                raise ToolUnavailable(f"the `{role}` tool was not found ({hint}; see config/tools.json / `q3tui tools check`)")
        except ToolUnavailable as exc:
            raise StepFailed(f"{self.name} not run: {exc}") from exc
        return tools

    async def run_tool(self, tools, role: str, script: Path, work: Path, log_name: str):
        """The role's tool on `script` (its log in `work`): (result, log text)."""
        from q3tui.eda import tools as toolmod
        res = await anyio.to_thread.run_sync(lambda: toolmod.run_role(
            tools, role, work, {"script": script, "workdir": work, "top": self.top_name}, log_name=log_name), abandon_on_cancel=True)
        log = Path(res.log_path).read_text(errors="replace") if res.log_path and Path(res.log_path).is_file() else ""
        return res, log

    top_name = ""  # (set by a step before run_tool: the {top} of the command template)

    # -- the fix loop ---------------------------------------------------------------------------------------------
    def round_limit(self, ctx) -> int:
        mx = self.options.get("max_rounds")
        return int(mx) if mx is not None else int(ctx.cfg.pipeline.max_fix_iterations)

    def rounds(self, ctx) -> tuple[dict, int]:
        """(this step's meta, the rounds it handed fixes upstream since it last passed). Counted across runs: a human gate upstream
        (eco_rtl, eco_patch) ends each run, so a per-run count would never reach the bound."""
        meta = ctx.engine.state.step_meta.setdefault(self.name, {})
        return meta, int(meta.get("rounds", 0))

    def reset_rounds(self, ctx) -> None:
        """The step passed, or gave up at the bound (your next run starts a fresh count)."""
        ctx.engine.state.step_meta.setdefault(self.name, {})["rounds"] = 0

    def hand_back(self, ctx, target: str, text: str) -> None:
        """A fix for `target` (an earlier step of this flow): it updates, then this step runs again (the engine's fix loop)."""
        meta, n = self.rounds(ctx)
        ctx.engine.request_change(target, text)
        meta["loop"], meta["rounds"] = True, n + 1

    # -- Workflow → Step → Task: the tasks of a step ---------------------------------------------------------------
    tasks: tuple[tuple[str, str], ...] = ()  # ((name, what it does), …): this step's tasks in order (its Tasks tab, docs/spec/eco-flow.md)

    def task(self, ctx, name: str, note: str = "", status: str = "done") -> None:
        """What task `name` of this step did in this run (done / skipped / waiting / handed / failed): a row of the step's Tasks tab, kept in
        schemas/eco_tasks.json. The first record of a run clears what the step's tasks did in the run before."""
        data = self.read(ctx.engine, TASKS_JSON, {}) or {}
        mine = dict(data.get(self.name) or {}) if getattr(ctx, "_eco_tasks", False) else {}
        ctx._eco_tasks = True
        mine[name] = {"status": status, "note": " ".join(str(note).split())[:400]}
        self.write(ctx.engine, TASKS_JSON, {**data, self.name: mine})

    # -- hand-off to the flow that owns the spec / the RTL (project mode) ---------------------------------------------
    def owner_made(self, engine, step: str) -> bool:
        """The owner flow's `step` (the spec flow's `spec`, the rtl flow's `rtl`) made what the ECO changes — its result, not your own files:
        that flow applies the ECO's change. (Your own spec / RTL: the ECO edits it itself, as on RTL from outside the project.)"""
        rec = engine.state.steps.get(step)
        return self.mode(engine) == "project" and rec is not None and rec.status == "done" and rec.origin != "user"

    async def hand_to_owner(self, ctx, flow: str, step: str, requests: list[str], key: str) -> str:
        """The change requests for `step` of the flow `flow` (queued once per `key`: a run again — after you reviewed or answered in that
        flow — does not send them twice), then that flow run on this project; its outcome (complete / gate / failed: …). This engine's
        state is saved before and the change requests for this flow pulled after (not `reload()`: see pull_requests)."""
        from q3tui import flows
        from q3tui.pipeline.engine import Engine
        meta = ctx.engine.state.step_meta.setdefault(self.name, {})
        ctx.engine.save()
        try:
            other = Engine(ctx.project, ctx.engine.bus, flow=flows.load_flow(flow, ctx.project.root))
            if meta.get("handed") != key or ctx.regenerate:  # (regenerate restored the ORG files: the change goes again)
                for r in requests:
                    other.request_change(step, r)
                meta["handed"] = key
            try:
                return await other.run(yes=self.auto_answer(ctx.engine) or ctx.engine.unattended_run())
            except StepFailed as exc:
                return f"failed: {exc}"
        finally:
            self.pull_requests(ctx)

    def pull_requests(self, ctx) -> None:
        """The change requests another flow's run wrote for this flow's steps (dv / Sanity hand-offs to eco_rtl / eco_spec), into this engine's
        state. (Not `reload()`: inside a step it replaces the state the engine records this step's result in — the result would be lost.)"""
        from q3tui.pipeline.state import PipelineState
        disk = PipelineState.load(ctx.engine.state_path)
        for s in ("eco_rtl", "eco_spec"):
            if disk.feedback.get(s):
                ctx.engine.state.feedback[s] = list(disk.feedback[s])

    # -- questions ------------------------------------------------------------------------------------------------
    def answers(self, engine) -> dict[str, str]:
        """Your answers, and the defaults accepted for you (run --yes, auto-approve)."""
        accepted = dict(engine.state.accepted_defaults.get(self.name, {}) or {})
        return {**accepted, **load_answers(self._q_paths(engine)[1])}

    def default_to_apply(self, q: dict) -> str | None:
        """An accepted default is a decision this step has not acted on yet: it runs again with it (`answers` reads it)."""
        return q.get("default_assumption") or None

    def ask(self, engine, key: str, prefix: str, question: str, options: list[tuple[str, str]], blocking: bool = True) -> str:
        """A question with a pick list, asked once per `key` (kept while unanswered, a new one when the key changes). Returns its id."""
        qs = self.questions_list(engine)
        answers = self.answers(engine)
        keyed = {q.id: q for q in qs}
        asked = (self.read(engine, self._asks_file(), {}) or {})
        for qid, k in asked.items():
            if k == key and qid in keyed:
                return qid
        q = Question(id="", question=question, blocking=blocking, kind="design_choice", default_assumption=options[0][0],
                     options=[QuestionOption(label=lab, description=desc) for lab, desc in options])
        # (never the id of an earlier question, even one with the same text: that one may be answered already)
        [q] = assign_question_ids([q], [], prefix, taken={x.id for x in qs} | set(answers))
        self.save_questions(engine, [*qs, q])
        asked[q.id] = key
        self.write(engine, self._asks_file(), asked)
        self.write_questions_file(engine)
        return q.id

    def auto_answer(self, engine) -> bool:
        """Questions answer themselves: `pipeline.auto_answer`, this step's gate mode `auto_answer` (pipeline.gate_modes), or --yes.
        (auto-approve alone still asks: its blocking questions wait for you.)"""
        pc = engine.project.cfg.pipeline
        return bool(pc.auto_answer or pc.gate_modes.get(self.name) == "auto_answer" or getattr(engine, "_yes", False))

    def decide(self, ctx, key: str, prefix: str, question: str, options: list[tuple[str, str]]) -> tuple[str | None, str | None]:
        """(question id, answer) of a decision: your answer, or None while it is awaited. Under auto-answer nobody is asked: the first
        option is taken and said (question id None)."""
        if self.auto_answer(ctx.engine):
            ctx.emit("warning", message=f"auto-answer: {question[:200]} → {options[0][0]}")
            return None, options[0][0]
        qid = self.ask(ctx.engine, key, prefix, question, options)
        return qid, self.answers(ctx.engine).get(qid)

    # -- the concerns of an AI change (eco_spec, eco_rtl): each one a question to you -----------------------------------------------
    def ask_concerns(self, ctx, key: dict, concerns: list[str], what: str) -> dict:
        """Each concern the AI reported with its change becomes a blocking question: keep the change, or your answer (it goes back to
        this step as a change request). {question id: {"concern": …}}. Under auto-answer nobody is asked: the change is kept, and said.
        `key` names the change (its diff in it: the same concern of a later revision is a new question)."""
        if self.auto_answer(ctx.engine):
            for c in concerns:
                ctx.emit("warning", message=f"auto-answer: {what} concern: {c[:200]} → {CONCERN_KEEP}")
            return {}
        k = sha256_json(key)[:12]
        asks = {}
        for c in concerns:
            # (a prefix per step: question ids are answered by id across the flow — ECOCSPEC1, ECOCRTL1)
            qid = self.ask(ctx.engine, f"concern:{k}:{sha256_json(c)[:12]}", f"ECOC{self.name.removeprefix('eco_').upper()}", (
                f"{what}: the AI reports a concern with its change — {c} Keep the change as it is, or tell what to do?"),
                [(f"{CONCERN_KEEP} (Recommended)", "the concern is accepted as it is: nothing changes"),
                 (f"{CONCERN_OWN}: <type what to change or decide>", f"your words go back to {self.name} as a change request")])
            asks[qid] = {"concern": c}
            ctx.emit("warning", message=f"{what}: concern — answer {qid}: {c[:200]}")
        return asks

    def concern_answers(self, ctx, prev: dict, key: dict) -> tuple[dict, list[str], list[str]]:
        """(the concern questions of the last change, your answers not acted on yet as change requests, the questions still open).
        Only the questions of the same requirement / ORG design (`key`) count; each answer is used once (`used`)."""
        asks = {q: dict(a) for q, a in (prev.get("concern_asks") or {}).items()} if prev.get("key") == key else {}
        answers = self.answers(ctx.engine)
        requests, open_ = [], []
        for qid, a in asks.items():
            if a.get("used"):
                continue
            answer = answers.get(qid)
            if answer is None:
                open_.append(qid)
                continue
            a.update(used=True, answer=answer)
            if answer_is(answer, CONCERN_KEEP, "keep", "giữ"):
                continue
            words = answer.strip()
            if answer_is(words, CONCERN_OWN):
                words = words[len(CONCERN_OWN):].lstrip(" :-").strip()
                words = "" if words.startswith("<") else words
            if not words:
                ctx.emit("warning", message=f"{qid}: no answer typed — the change is kept; send a change request to {self.name} yourself")
                continue
            requests.append(f"From your answer to {qid} (a concern of the last change: {a['concern']}): {words}")
        return asks, requests, open_

    def _asks_file(self) -> str:
        return f"questions/{self.name}.keys.json"


def answer_is(answer: str | None, *words: str) -> bool:
    """The answer starts with one of `words` (a pick-list label, or what you typed)."""
    a = (answer or "").strip().lower()
    return any(a.startswith(w.lower()) for w in words)
