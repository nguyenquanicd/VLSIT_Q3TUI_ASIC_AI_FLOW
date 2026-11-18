"""ECO step `eco_verify` (project mode): Verification (the dv flow) and Sanity again on the ECO'd design, before the netlist ECO. You are asked
whether to run them (the `verify` option answers for you; auto-answer takes yes). Yes: the dv flow, then the Sanity flow (analysis, then the
review's hand-off) run within this step; both must pass before `eco_patch`. Their RTL / spec fixes come back to this flow (`eco_rtl` /
`eco_spec`, the smallest change, judged first: lib/ref.py `eco_owner`), never to the rtl flow's generator: this step hands back, the fix loop
updates RTL(F) and runs this step again (bounded by `max_rounds`). A request `eco_rtl` judged not the ECO's to fix ends here, for you to look at.
External mode (a fire-fighting ECO) and "no": skipped."""
from __future__ import annotations

from pathlib import Path

from q3tui.core.project import read_json
from q3tui.flows.eco.lib.base import RTL_JSON, SPEC_JSON, VERIFY_JSON, EcoStep, answer_is
from q3tui.pipeline.base import StepContext, StepFailed

YES, NO = "Yes, run dv and Sanity again", "No, go on to the netlist ECO"
NOT_PASSED = ("FAIL", "ERROR", "TIMEOUT", "BLOCKED")


class Step(EcoStep):
    name = "eco_verify"
    title = "Verification + Sanity on the ECO'd design"
    deps = ("eco_rtl",)
    hashed_options = ("verify",)

    def inputs(self, engine) -> list[Path]:
        files = [self.artifact(engine, RTL_JSON), self.artifact(engine, SPEC_JSON), *self.rtl_f_files(engine), self._q_paths(engine)[1]]
        return [f for f in files if f.is_file()]

    def outputs(self, engine) -> list[Path]:
        return [f for f in (self.artifact(engine, VERIFY_JSON),) if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *self._q_paths(engine)]

    def missing_input(self, engine) -> str | None:
        if not self.artifact(engine, RTL_JSON).is_file():
            return "RTL(F) is needed first (step eco_rtl)"
        return None

    def _wanted(self, ctx: StepContext) -> bool | None:
        opt = self.options.get("verify")
        if opt is not None:
            return str(opt).strip().lower() in ("1", "true", "yes", "on")
        qid, answer = self.decide(ctx, "verify", "ECOVER", (
            "The ECO changed this project's RTL (and spec). Run Verification (the dv flow) and Sanity (CDC / RDC) again on it before the netlist "
            "ECO? Yes: both must pass first; their RTL fixes come back to eco_rtl as the smallest change."),
            [(f"{YES} (Recommended)", "the netlist ECO starts only when dv and Sanity pass on the new RTL"),
             (NO, "the netlist ECO goes on; dv / Sanity are yours to run later")])
        if answer is None:
            ctx.emit("warning", message=f"ECO verify: answer {qid} (run dv + Sanity again or not), then run again")
            return None
        return not answer_is(answer, "no")

    async def run(self, ctx: StepContext) -> None:
        engine = ctx.engine
        if self.mode(engine) != "project":
            self.write(engine, VERIFY_JSON, {"status": "skipped", "why": "external RTL: a fire-fighting ECO, no dv / Sanity request"})
            ctx.emit("log", message="ECO verify: skipped (external RTL)")
            return
        wanted = self._wanted(ctx)
        if wanted is None:
            self.write(engine, VERIFY_JSON, {"status": "waiting"})
            return
        if not wanted:
            self.write(engine, VERIFY_JSON, {"status": "skipped", "why": "your choice: dv / Sanity not run again"})
            ctx.emit("log", message="ECO verify: skipped (your choice)")
            return
        yes = self.auto_answer(engine) or engine.unattended_run()
        results: dict[str, dict] = {}
        failed = None
        for flow in ("dv", "sanity"):
            ok, note = await (self._dv(ctx, yes) if flow == "dv" else self._sanity(ctx, yes))
            results[flow] = {"passed": ok, "note": note}
            ctx.emit("log" if ok else "warning", message=f"ECO verify: {flow} {'passed' if ok else 'did not pass'} — {note}")
            if not ok:
                failed = flow
                break
        prev = self.read(engine, VERIFY_JSON, {}) or {}
        declined = len((self.read(engine, RTL_JSON, {}) or {}).get("declined", []))
        if failed is None:
            self.write(engine, VERIFY_JSON, {"status": "passed", "flows": results})
            self.reset_rounds(ctx)
            return
        fixes = {s: list(engine.state.feedback.get(s) or []) for s in ("eco_rtl", "eco_spec") if engine.state.feedback.get(s)}
        record = {"status": "fixes" if fixes else "failed", "flows": results, "handed": fixes, "declined": declined}
        meta, n = self.rounds(ctx)
        if fixes and declined > int(prev.get("declined", declined)) and prev.get("status") == "fixes":
            fixes = {}  # (eco_rtl kept the RTL for the last requests and the check still fails: not a loop to go on with)
        if fixes and n < self.round_limit(ctx):
            meta["loop"], meta["rounds"] = True, n + 1  # (the requests are queued already: eco_rtl / eco_spec update, then this step again)
            self.write(engine, VERIFY_JSON, record)
            ctx.emit("log", message=f"ECO verify: {failed} handed {sum(map(len, fixes.values()))} fix(es) to "
                                    f"{', '.join(fixes)} (round {n + 1}); they run next, then dv / Sanity again")
            return
        record["status"] = "failed"
        self.write(engine, VERIFY_JSON, record)
        self.reset_rounds(ctx)
        last = (self.read(engine, RTL_JSON, {}) or {}).get("declined", [])
        why = f"; eco_rtl kept the RTL: {last[-1]['why'][:300]}" if last else ""
        raise StepFailed(f"ECO verify: {failed} does not pass on the ECO'd design — {results[failed]['note']}{why}. Look at it (q3tui --flow "
                         f"{failed}), then run eco again (or answer no to eco_verify's question to go on without it)")

    def _pull_requests(self, ctx: StepContext) -> None:
        """The change requests the other flow's hand-off wrote for this flow's steps, into this engine's state. (Not `reload()`: inside a
        step it replaces the state the engine records this step's result in — the result would be lost.)"""
        from q3tui.pipeline.state import PipelineState
        disk = PipelineState.load(ctx.engine.state_path)
        for s in ("eco_rtl", "eco_spec"):
            if disk.feedback.get(s):
                ctx.engine.state.feedback[s] = list(disk.feedback[s])

    async def _other(self, ctx: StepContext, name: str, yes: bool) -> str:
        """Run the flow `name` on this project (its own engine; this one saved before, its requests pulled after)."""
        from q3tui import flows
        from q3tui.pipeline.engine import Engine
        ctx.engine.save()
        try:
            other = Engine(ctx.project, ctx.engine.bus, flow=flows.load_flow(name, ctx.project.root))
            try:
                return await other.run(yes=yes)
            except StepFailed as exc:
                return f"failed: {exc}"
        finally:
            self._pull_requests(ctx)

    def _left(self, ctx, name: str) -> list[str]:
        from q3tui import flows
        from q3tui.pipeline.engine import Engine
        views = Engine(ctx.project, flow=flows.load_flow(name, ctx.project.root)).status()
        return [f"{v.name} ({v.status})" for v in views if v.status not in ("done", "user")]

    async def _dv(self, ctx: StepContext, yes: bool) -> tuple[bool, str]:
        outcome = await self._other(ctx, "dv", yes)
        left = self._left(ctx, "dv")
        tests = (read_json(ctx.project.schemas_dir / "dv_test_results.json", {}) or {}).get("tests", [])
        bad = [f"{t.get('name') or t.get('tc_id')}: {t.get('status')}" for t in tests if t.get("status") in NOT_PASSED]
        if outcome == "complete" and not left and not bad and tests:
            return True, f"{len(tests)} test(s) passed"
        return False, (f"ended '{outcome}'" + (f"; not done: {', '.join(left[:5])}" if left else "")
                       + (f"; {len(bad)} test(s) not passing: {', '.join(bad[:5])}" if bad else "") + ("" if tests else "; no test result"))

    async def _sanity(self, ctx: StepContext, yes: bool) -> tuple[bool, str]:
        from q3tui.core.loop import measure
        outcome = await self._other(ctx, "sanity", yes)
        if outcome not in ("complete", "gate"):
            return False, f"analysis ended '{outcome}'"
        n_open, total = measure(ctx.project)
        if n_open == 0:
            return True, f"nothing open ({total} found, all waived or fixed)"
        # (the review's fix_rtl / spec decisions: handed to this flow's eco_rtl / eco_spec while the project-mode ECO is on)
        from q3tui import flows
        from q3tui.core.ops import Ops
        from q3tui.pipeline.engine import Engine, EngineError
        ctx.engine.save()
        try:
            msg = Ops(Engine(ctx.project, ctx.engine.bus, flow=flows.load_flow("sanity", ctx.project.root))).run_action("sanity_handoff")
        except EngineError as exc:
            msg = f"nothing handed off ({exc})"
        finally:
            self._pull_requests(ctx)
        return False, f"{n_open} of {total} open; {msg}"
