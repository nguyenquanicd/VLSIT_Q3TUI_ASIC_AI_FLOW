"""The dv flow's simulation triage: whose fault is a failing test, and where the fix goes (rule: a step never works around an earlier step's problem, it hands it back).

`simulate` calls `handle_failures` with the tests that did not pass. A second LLM stage (fresh session, read only; it may read the RTL, which the testbench stages may not) gives a
verdict per failure and code dispatches it, the way the rtl flow's smoke test does:

- `tb_bug`: a change request for the `tb` step, scoped to that test (`[tb:TC-019] …`), or to the shared tb_top when the verdict says `module: top` (`[tb:top] …`: a small session on
  tb_top.sv; the test cases stay unless they use what changed); the UVM kind: the whole step. `simulate` goes on normally and marks its loop: the engine updates `tb`,
  then `simulate` runs again. Bounded by `options.max_rounds` or `pipeline.max_fix_iterations`.
- `rtl_bug`: a change request for the `rtl` step of the flow that owns the RTL (`handoff_flow` of the tb options, default `rtl`), scoped to the module (`[rtl:<module>] …`). That flow has to run
  to apply it; the RTL is an input of `tb`, so `tb` and `simulate` then run again on the new RTL. In an unattended run (`engine.unattended_run`) the fix loop runs that flow itself
  (`engine.hand_to_flow`), bounded like the tb fixes; a round after which the RTL did not change, or the failures did not go down, stops it. Otherwise `simulate` stays failed until you run it.
- `spec_issue` / `unsure`, or a failure that keeps coming back after its fix was handed over: a blocking question for you (spec_gap / design_choice); nothing is changed.
  The triage gives the ways to settle it (`options`, the recommended one first: the pick list, and the default), and the decision it waits for (`decision`):
  the failures that wait for the same decision are one question. In an unattended run a fix that keeps coming back first gets one wider try instead of the
  question (what was tried; a testbench fix goes to tb_top and the test). A round that only asks counts as a round, and the answers an unattended run gives
  with the defaults do not start the rounds over (yours do): it stops at the bound instead of asking forever.

A failing test that passed with an earlier version of the project (Q3TUI's history, core/history.py: `simulate` keeps the version each test last
passed with) is a regression: the prompt says which versions changed the RTL since (the flow and step that made them), the other files changed
since, and the RTL diff; the change request of a module carries that module's diff since, so the rtl step fixes the change rather than starting over.

A module a generator made (the rtl flow's csr step: `src/rtl/csr/provided.json`) is named in the prompt: a bug in it is an `rtl_bug` (the rtl step changes it in
place and keeps the change as a patch that outlives the next generation), unless your spec forbids editing it or the rtl option `keep_generated` is on: then it
is a `spec_issue` with the choices.

Every verdict is in `schemas/dv_triage.json`. Models of the LLM's answer: `flows/rtl/lib/models.Verdict` (the same as the smoke triage's)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from q3tui.core.project import write_json
from q3tui.flows import skill_sections
from q3tui.flows.rtl.lib import skills as skillmod
from q3tui.flows.rtl.lib.models import Verdict
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext, StepFailed
from q3tui.steps.common import Question, assign_question_ids, load_answers, scoped, spec_block

TRIAGE = skill_sections(Path(__file__).parent / "md" / "triage.md")["TRIAGE"]
TRIAGE_JSON = "dv_triage.json"
DV_FLOW_FILE = Path(__file__).parent / "FLOW.md"  # (the skill is found next to the dv flow whichever flow file runs its steps: a project's own flow file has no skills/ folder)
SINCE_DIFF_LINES = 300  # the RTL diff the triage gets per version tests passed with
MODULE_DIFF_LINES = 150  # a module's diff in its change request


class DvTriage(BaseModel):
    verdicts: list[Verdict]


def _log_tail(project, log: str, n: int = 40) -> str:
    p = project.root / log if log and not Path(log).is_absolute() else Path(log) if log else None
    if p is None or not p.is_file():
        return "(no log)"
    return "\n".join(p.read_text(errors="replace").splitlines()[-n:])


def _requirements(project) -> dict[str, str]:
    from q3tui.flows.spec.lib import artifacts

    spec = artifacts.read(project, "structured_spec.json") or {}
    return {r["req_id"]: r.get("text", "") for r in spec.get("requirements", []) if r.get("req_id")}


def _rtl_files(project, rtl_dir: Path) -> list[Path]:
    return sorted(p for p in rtl_dir.rglob("*") if p.is_file() and p.suffix in (".sv", ".v", ".svh", ".vh")) if rtl_dir.is_dir() else []


def reset(engine, step) -> None:
    """The tests pass: the fix rounds and what was handed over start afresh."""
    meta = engine.state.step_meta.setdefault(step.name, {})
    meta.update({"rounds": 0, "loop": False})
    meta.pop("history", None)
    meta.pop("flow_round", None)


def rtl_hash(files: list[Path]) -> str:
    import hashlib

    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:16]


def since_pass(project, failures: list[dict], rtl_dir: Path) -> dict[str, dict]:
    """The failing tests that passed with an earlier version of the project (their `passed`: {rev, at}), per version: {tests, at, versions (the ones
    since that changed the RTL, newest first), changed (every file changed since), diff (the RTL's, that version → now)}."""
    from q3tui.core import history

    now = history.head(project) if history.enabled(project) else None
    if not now:
        return {}
    rtl = project.rel(rtl_dir)
    out: dict[str, dict] = {}
    for f in failures:
        p = f.get("passed") or {}
        if p.get("rev") and p["rev"] != now:
            out.setdefault(p["rev"], {"tests": [], "at": str(p.get("at") or "")})["tests"].append(f["id"])
    for rev, g in list(out.items()):
        try:
            g["versions"] = history.versions(project, limit=20, paths=[rtl], since=rev, files=True)
            g["changed"] = history.changed(project, rev)
            g["diff"] = history.diff(project, rev, paths=[rtl], max_lines=SINCE_DIFF_LINES)
        except history.HistoryError:
            out.pop(rev)  # (a version the history does not have: nothing to compare with)
    return out


def _since_pass_block(since: dict[str, dict], rtl: str) -> list[str]:
    if not since:
        return []
    parts = ["## Tests that passed before: what changed since (Q3TUI's history of the project, ground truth)",
             "A test that passed with an earlier version and fails now most likely fails because of a change made since: look there first.", ""]
    for rev, g in since.items():
        parts.append(f"### {', '.join(g['tests'])}: passed with version {rev[:8]} ({g['at'][:16].replace('T', ' ')})")
        parts.append("Versions since that changed the RTL (newest first):" if g["versions"] else "No version since changed the RTL: it is the same as then.")
        parts += [f"- {v.short} {v.when} {v.title}: {', '.join(Path(x).name for x in v.files)}" for v in g["versions"]]
        other = [x for x in g["changed"] if not x.startswith(rtl + "/")]
        if other:
            parts.append(f"Other files changed since: {', '.join(other[:30])}{' …' if len(other) > 30 else ''}")
        if g["diff"]:
            parts += ["The RTL diff, that version → now:", "```diff", g["diff"], "```"]
        parts.append("")
    return parts


def _module_since_pass(project, since: dict[str, dict], module_file: Path | None, tests: list[str]) -> str:
    """For a module's change request: its change since the version its failing tests passed with, and who made it."""
    from q3tui.core import history

    if module_file is None:
        return ""
    rel = project.rel(module_file)
    for rev, g in since.items():
        mine = sorted(set(tests) & set(g["tests"]))
        if not mine:
            continue
        try:
            d = history.diff(project, rev, paths=[rel], max_lines=MODULE_DIFF_LINES)
        except history.HistoryError:
            continue
        if d:
            who = [f"{v.when} {v.title}" for v in g["versions"] if rel in v.files]
            return (f"\n\n{', '.join(mine)} passed with an earlier version of this module ({rev[:8]}, {g['at'][:16].replace('T', ' ')}); it changed since "
                    f"({'; '.join(who) or 'see the diff'}):\n```diff\n{d}\n```\nFind what that change broke and fix it: keep what it was made for "
                    "(timing, area, …) where that can be done correctly, else go back to the earlier code.")
    return ""


def failure_summary(failures: list[dict]) -> str:
    return "\n".join(f"- {f['id']}{' (' + f['name'] + ')' if f.get('name') else ''}: {f['note']}" for f in failures)


async def handle_failures(step, ctx: StepContext, failures: list[dict], rtl_dir: Path, kind: str, original: str) -> None:
    """Triage the failing tests and dispatch the verdicts. `failures`: {id, name, note, log, reqs}; `kind`: plain | uvm (a testbench change request is scoped to the test only for plain);
    `original`: the failure message the step gives when the triage cannot run. Returns when something was dispatched to this flow (the fix loop runs); raises StepFailed when it is waiting
    for you or for another flow."""
    engine, project, cfg = ctx.engine, ctx.project, ctx.cfg
    lay = step.lay(engine)
    summary = failure_summary(failures)
    meta = engine.state.step_meta.setdefault(step.name, {})
    auto = set(meta.get("auto_answers") or [])  # (answered with their defaults by an unattended run: engine._auto_answer_failure)
    answered = len([q for q in load_answers(step._q_paths(engine)[1]) if q not in auto])
    if ctx.regenerate or "rounds" not in meta or meta.get("answered") != answered:
        meta["rounds"] = 0  # (counted until the tests pass, you regenerate, or you answer — not an automatic answer: not per run, or a limit every run starts over is never reached)
    meta["answered"] = answered
    meta["loop"] = False
    rounds = int(meta["rounds"])
    from q3tui.flows.dv import uvm

    tb_opts = uvm.tb_options(engine)
    limit = int(tb_opts.get("max_rounds") or cfg.pipeline.max_fix_iterations)
    if rounds >= limit:
        raise StepFailed(f"simulate: still failing after {rounds} fix round(s) (options.max_rounds / pipeline.max_fix_iterations):\n{summary}")
    history: list[dict] = meta.setdefault("history", [])
    reqs = _requirements(project)
    rtl = _rtl_files(project, rtl_dir)
    now_rtl = rtl_hash(rtl)
    since = since_pass(project, failures, rtl_dir)
    last = meta.pop("flow_round", None)  # the RTL fixes the last round had the owner flow apply in this run
    stalled = ("the RTL did not change" if last and last.get("rtl") == now_rtl
               else f"the failures did not go down ({last.get('failed')} → {len(failures)})" if last and len(failures) >= int(last.get("failed") or 0) else "")
    tb_files = sorted(p for p in lay.tb.rglob("*") if p.is_file() and p.suffix in (".sv", ".svh", ".f")) if lay.tb.is_dir() else []
    skills = skillmod.discover(project.config_dir, DV_FLOW_FILE, ["sim-triage"])  # (the method is a playbook skill: yours in config/skills/ wins, as for the rtl flow's smoke-triage)
    block, _ = spec_block(project)
    parts = ["# Task: triage the failing simulation tests", "", "## Specification", block, "",
             "## Requirements", "\n".join(f"- {k}: {v}" for k, v in reqs.items()) or "(none)", "",
             f"## Files (read them): testbench ({kind}) {', '.join(project.rel(p) for p in tb_files[:40])}; RTL {', '.join(project.rel(p) for p in rtl[:40])}", "",
             *_generated_block(rtl_dir, cfg),
             *_since_pass_block(since, project.rel(rtl_dir)),
             "## Already handed over in earlier rounds (do not ask for the same again: say if it did not work, and why)",
             "\n".join(f"- {h['key']}" + (" (the wider try)" if h.get("widened") else "") + (f": {h['req'][:200]}" if h.get("req") else "") for h in history[-10:])
             or "(nothing yet)", "", "## The failing tests (ground truth)"]
    for f in failures:
        parts += [f"### {f['id']} {f.get('name', '')}", f"status: {f['note']}", f"requirements: {', '.join(f.get('reqs') or []) or '–'}", f"log {f.get('log') or '(none)'} (end):",
                  "```", _log_tail(project, f.get("log") or ""), "```", ""]
    parts.append(skillmod.index(skills, project.root))
    stage = Stage(name="dv_triage", system_prompt=TRIAGE, prompt="\n".join(parts), cwd=project.root, builtin_tools=["Read", "Grep", "Glob"], add_dirs=skillmod.add_dirs(skills), output_model=DvTriage,
                  deny_dirs=[project.model_dir, project.arch_dir, project.src_dir / "sva"], max_turns=ctx.cfg.tb.max_turns)
    try:
        verdicts: list[Verdict] = (await ctx.llm(stage)).output.verdicts
    except StepFailed:
        raise
    except Exception as exc:  # noqa: BLE001 - no credentials, a stage that failed: the tests failed all the same
        raise StepFailed(f"{original}\n(the triage could not run: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__})") from exc

    modules = {p.stem for p in rtl}
    known = {f["id"] for f in failures}
    asks: list[Question] = []
    to_tb = 0
    by_module: dict[str, list[Verdict]] = {}
    by_decision: dict[str, list[Verdict]] = {}  # (failures that wait for the same decision: one question)
    seen: dict[str, int] = {}
    for h in history:  # (an RTL fix counts once the RTL changed after it: one handed over and never applied was not tried)
        if not h["key"].startswith("rtl_bug|") or h.get("rtl") not in (None, now_rtl):
            seen[h["key"]] = seen.get(h["key"], 0) + 1
    report = {"round": rounds + 1, "failures": failures, "verdicts": []}
    wider: dict[str, str] = {}  # rtl unit → what the earlier tries were (the wider try of a fix that keeps coming back)
    for v in verdicts:
        report["verdicts"].append(v.model_dump())
        unit = v.module if v.module in modules else next(iter(sorted(modules)), "")
        top = v.verdict == "tb_bug" and kind == "plain" and v.module.strip().lower().removesuffix(".sv") in ("top", "tb_top")  # (the shared tb_top, not the test)
        key = f"{v.verdict}|{unit if v.verdict == 'rtl_bug' else 'top' if top else v.id}|{v.id}"
        again = v.verdict in ("rtl_bug", "tb_bug") and bool(v.request.strip()) and seen.get(key, 0) >= cfg.pipeline.escalate_after_repeats
        # it keeps coming back after its fix: an unattended run makes one wider try (what was tried, where else to look) instead of a question nobody reads
        widen = again and engine.unattended_run() and not any(h["key"] == key and h.get("widened") for h in history)
        tried = "; ".join(h["req"][:200] for h in history if h["key"] == key and h.get("req")) or "(not recorded)"
        more = (f"\n\nThis failure came back {seen.get(key, 0)} time(s) after its fix (tried: {tried}). Look wider and fix the cause"
                + (": the shared tb_top.sv (its monitors, checkers, helper tasks) as well as the test." if v.verdict == "tb_bug" else
                   ": the module's interfaces with its neighbours and the cycle the spec states, not only the line named before.")) if widen else ""
        if again and not widen:
            asks.append(Question(id="", blocking=True, kind="design_choice", question=(
                f"Test {v.id} keeps failing ({v.verdict.replace('_', ' ')}{' in ' + unit if v.verdict == 'rtl_bug' and unit else ''}, {seen[key] + 1} times): {v.summary} How should it be settled?"),
                default_assumption="Keep the spec as the reference and change the implementation once more, starting from the evidence."))
        elif v.verdict == "rtl_bug" and v.request.strip():
            by_module.setdefault(unit, []).append(v)
            history.append({"key": key, "round": rounds + 1, "rtl": now_rtl, "req": v.request.strip(), **({"widened": True} if widen else {})})
            if widen:
                wider[unit] = more
        elif v.verdict == "tb_bug" and v.request.strip():
            history.append({"key": key, "round": rounds + 1, "req": v.request.strip(), **({"widened": True} if widen else {})})
            text = f"From the simulation triage ({v.id}): {v.summary} {v.request}" + more
            if kind != "plain":
                engine.request_change("tb", text)
            else:
                for where in (["top", v.id] if widen else ["top"] if top else [v.id]):
                    if where == "top" or where in known:
                        engine.request_change("tb", scoped("tb", where, text))
            ctx.emit("log", message=f"simulate {v.id}: testbench bug → tb{' (tb_top)' if top else ''}: {v.summary[:100]}"
                                    + (f" — came back {seen.get(key, 0)} time(s): one wider try (tb_top and the test) instead of a question" if widen else ""))
            to_tb += 1
        else:
            by_decision.setdefault(v.decision.strip().lower() or v.id, []).append(v)
    asks += [vs[0].question("Test", [v.id for v in vs]) for vs in by_decision.values()]
    answers = load_answers(step._q_paths(engine)[1])
    kept = [q for q in step.questions_list(engine) if q.id in answers]
    step.save_questions(engine, [*kept, *assign_question_ids(asks, kept, "SIM", taken=set(answers))])
    write_json(lay.schemas / TRIAGE_JSON, report)
    if to_tb:
        meta["loop"], meta["rounds"] = True, rounds + 1  # the engine updates tb on the change requests, then runs simulate again
    # the hand-over to the other flow last: it saves this engine's state, lets the other flow's engine write the change request into the same file, and reads it back
    handed: list[str] = []
    owner = str(tb_opts.get("handoff_flow") or "rtl")
    for unit, vs in by_module.items():
        text = scoped("rtl", unit, f"From the simulation of the testbench ({', '.join(v.id for v in vs)}): " + " | ".join(f"{v.summary} {v.request}" for v in vs)
                      + _module_since_pass(project, since, next((p for p in rtl if p.stem == unit), None), [v.id for v in vs]) + wider.get(unit, ""))
        owner = _hand_to_rtl_flow(ctx, owner, text)
        ctx.emit("log", message=f"simulate {', '.join(v.id for v in vs)}: RTL bug → {owner}:rtl ({unit}): {vs[0].summary[:100]}"
                                + (" — came back after its fix: one wider try instead of a question" if unit in wider else ""))
        handed.append(f"{unit} → {owner}")
    meta = engine.state.step_meta.setdefault(step.name, {})  # (the hand-over reloaded the state: this step's meta is a new object)
    run_owner = bool(handed) and engine.unattended_run() and not stalled
    if run_owner:  # the fix loop runs the owner flow within this run, then tb and simulate on the new RTL
        engine.hand_to_flow(step.name, owner)
        meta["rounds"], meta["flow_round"] = rounds + 1, {"rtl": now_rtl, "failed": len(failures)}
        ctx.emit("log", message=f"simulate: the {owner} flow runs next for {', '.join(handed)}, then tb and simulate again")
    if to_tb or run_owner:
        if (handed and not run_owner) or asks:
            said = [("also handed to the RTL flow: " + ", ".join(handed) + (f" ({stalled} after the last {owner} flow run: run it yourself)" if stalled else ""))
                    if handed and not run_owner else "", f"{len(asks)} question(s) wait for you" if asks else ""]
            ctx.emit("warning", message="; ".join(x for x in said if x))
        return
    if handed:
        why = f"{stalled} after the {owner} flow ran for the last fixes; " if stalled else ""
        raise StepFailed(f"simulate: RTL bug(s) handed to the {owner} flow ({'; '.join(handed)}): {why}run it (q3tui --flow {owner} run), then this flow again: the RTL is an input of tb, "
                         f"so tb and simulate run on the new RTL.\n{summary}")
    if not asks:
        raise StepFailed(f"simulate: the triage gave no verdict to act on:\n{summary}")
    meta["rounds"] = rounds + 1  # (a round that only asks counts too: answered with the defaults by an unattended run, it must not go on forever)
    ids = ", ".join(q["id"] for q in engine.questions() if q["step"] == step.name and q["status"] == "open")
    raise StepFailed(f"simulate: the tests are failing and need your decision on {ids or 'the open questions'} (answer them, then run again):\n{summary}")


def _generated_block(rtl_dir: Path, cfg) -> list[str]:
    """The prompt's part on the RTL modules a generator made (the rtl flow's csr step): whether a bug in one can be an rtl_bug."""
    from q3tui.flows.rtl.lib import csr

    made = sorted(csr.read_provided(rtl_dir))
    if not made:
        return []
    if (cfg.pipeline.step_options.get("rtl") or {}).get("keep_generated"):
        how = ("Settings → rtl \"Never edit generated RTL\" is on: they are never changed, so a bug in one is a spec_issue whose proposal names the choices "
               "(fix the generator, revise the spec to the generated behaviour, or turn the setting off).")
    else:
        how = ("The rtl flow changes them in place on an RTL change request (name, ports and registers kept) and keeps the change as a patch "
               "(src/rtl/csr/patches/) applied again when the module is generated again: a bug in one is an rtl_bug for it, unless the specification "
               "forbids editing it; then it is a spec_issue whose proposal names the choices (fix the generator, allow the change in place, or revise the spec).")
    return ["## Generated RTL", f"Made by the APB-CSR-Generator (the rtl flow's csr step), not by hand: {', '.join(made)}. {how}", ""]


def _hand_to_rtl_flow(ctx: StepContext, flow_name: str, text: str) -> str:
    """A change request for the `rtl` step of the flow that owns the RTL (the way the FPGA flow hands over a PPA fix); returns the flow's name."""
    from q3tui import flows
    from q3tui.pipeline.engine import Engine

    owner = flows.load_flow(flow_name, ctx.project.root)
    if owner.name == ctx.engine.flow.name:
        raise StepFailed("handoff_flow is this flow itself: the RTL is the rtl flow's")
    ctx.engine.save()  # what this process holds is on disk; the other flow's engine reads and writes the same pipeline.json
    other = Engine(ctx.project, flow=owner)
    if "rtl" not in other.by_name:
        raise StepFailed(f"flow '{owner.name}' has no step 'rtl' to hand the RTL fix to")
    other.request_change("rtl", text)
    ctx.engine.reload()  # (the change request is in the state now)
    return owner.name
