"""ECO step `eco_rtl`: RTL(F). Code copies the ORG RTL to `eco/rtl/` (with its filelist); an LLM stage edits that copy to do what the requirement
asks (it may write only there; the netlists, the patch and build/ are denied). Code then writes `eco/rtl.diff` and parses RTL(F) (pyslang): an
error goes back to the LLM once, then fails the step. A change request (your review, EQ(2)) edits the current RTL(F); a changed requirement or
ORG RTL starts again from a fresh copy.

Before any edit a read-only stage plans the smallest change (an ECO changes as little as it can). When the requirement or a change request
prescribes how to make the change and the plan finds a smaller one with the same required function, you are asked (blocking): the smaller
change (recommended; auto-answer takes it), the change as asked, or your own words. The decision is kept with the request it answers."""
from __future__ import annotations

import difflib
import shutil
from pathlib import Path

from q3tui.core.project import sha256_file, sha256_json
from q3tui.flows import skill_sections
from q3tui.flows.eco.lib.base import EQ1_JSON, INPUTS_JSON, RTL_JSON, SPEC_JSON, EcoStep, answer_is
from q3tui.flows.eco.lib.models import RtlPlan, RtlUpdate
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext, StepFailed

SYSTEM = skill_sections(Path(__file__).parent / "md" / "skill.md")
PLAN_JSON = "eco_rtl_plan.json"  # schemas/: the plan of the pending change, the request it answers, the decision
USE_ALT, KEEP, OWN = "Use the smaller change", "Keep the change as asked", "My own way"


def chosen_change(answer: str, plan: dict) -> str:
    """The change to make, from your answer to the smaller-change question."""
    alt = plan.get("alternative") or {}
    if answer_is(answer, USE_ALT, "smaller", "use"):
        return f"{alt.get('change', '')} (the smaller change, chosen by the user: {alt.get('differs_from_request', '')})"
    if answer_is(answer, KEEP, "keep", "as asked"):
        return f"{plan.get('requested') or plan.get('plan', '')} (as asked: the user declined the smaller change)"
    text = answer.strip()
    if answer_is(text, OWN):
        text = text[len(OWN):].lstrip(" :-").strip()
    return f"{text} (the user's own way)"


def copy_names(files: list[Path]) -> dict[Path, str]:
    """The name of each ORG file in eco/rtl/: its own, or `<parent>__<name>` when two files share a name."""
    seen: dict[str, int] = {}
    for f in files:
        seen[f.name] = seen.get(f.name, 0) + 1
    return {f: (f.name if seen[f.name] == 1 else f"{f.parent.name}__{f.name}") for f in files}


def unified_diff(project, pairs: list[tuple[Path, Path]]) -> str:
    out = []
    for org, new in pairs:
        a = org.read_text(errors="replace").splitlines(keepends=True) if org.is_file() else []
        b = new.read_text(errors="replace").splitlines(keepends=True) if new.is_file() else []
        out += difflib.unified_diff(a, b, fromfile=f"a/{project.rel(org)}", tofile=f"b/{project.rel(new)}")
    return "".join(out)


class Step(EcoStep):
    name = "eco_rtl"
    title = "RTL(F): the RTL updated to the requirement"
    deps = ("eco_spec",)

    def inputs(self, engine) -> list[Path]:
        req = self.requirement(engine)
        spec = [self.artifact(engine, SPEC_JSON), self.spec_diff(engine)] if self.mode(engine) == "project" else []
        return [self.artifact(engine, INPUTS_JSON), self.artifact(engine, EQ1_JSON), *([req] if req else []), *self.org_rtl_files(engine),
                *[f for f in spec if f.is_file()], self._q_paths(engine)[1]]

    def outputs(self, engine) -> list[Path]:
        files = [self.artifact(engine, RTL_JSON), self.rtl_diff(engine), self.rtl_f_filelist(engine), *self.rtl_f_files(engine)]
        return [f for f in files if f.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), self.artifact(engine, PLAN_JSON), *self._q_paths(engine)]

    def missing_input(self, engine) -> str | None:
        miss = self.need_inputs(engine)
        if miss:
            return miss
        status = (self.read(engine, EQ1_JSON, {}) or {}).get("status")
        if status not in ("equivalent", "skipped"):
            return "EQ(1) has to pass (or be skipped) first (step eco_eq1)"
        if self.mode(engine) == "project" and not (self.read(engine, SPEC_JSON, {}) or {}).get("status"):
            return "the spec update first (step eco_spec)"
        return None

    def _fresh_copy(self, engine) -> dict[str, str]:
        """eco/rtl/ = the ORG RTL again, with a filelist of the copies (the ORG include dirs and defines kept). {copy: ORG file}.
        Project mode: the project's RTL files are the ORG ones again (from ref/; the filelist is the project's own). {RTL file: ref copy}."""
        from q3tui.hdl.filelist import parse_filelist
        project = engine.project
        if self.mode(engine) == "project":
            ref = self.ref_dir(engine)
            mapping = {}
            for org in self.org_rtl_files(engine):
                dst = project.root / org.relative_to(ref)
                if not dst.is_file() or dst.read_bytes() != org.read_bytes():
                    project.backup([dst])
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(org, dst)
                mapping[project.rel(dst)] = project.rel(org)
            return mapping
        fl = parse_filelist(self.org_filelist(engine), project.root)
        d = self.rtl_f_dir(engine)
        if d.is_dir():
            project.backup([p for p in d.rglob("*") if p.is_file()])
            shutil.rmtree(d)
        d.mkdir(parents=True)
        names = copy_names(fl.files)
        mapping = {}
        for org, name in names.items():
            shutil.copyfile(org, d / name)
            mapping[project.rel(d / name)] = project.rel(org)
        lines = [f"+incdir+{x}" for x in fl.incdirs] + [f"+define+{k}" + (f"={v}" if v is not None else "") for k, v in fl.defines.items()]
        lines += list(mapping)
        self.rtl_f_filelist(engine).write_text("\n".join(lines) + "\n")
        return mapping

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        req = self.requirement(engine)
        prev = self.read(engine, RTL_JSON, {}) or {}
        key = {"requirement": sha256_file(req), "org": {project.rel(f): sha256_file(f) for f in self.org_rtl_files(engine)}}
        pending = self.read(engine, PLAN_JSON, {}) or {}
        feedback = list(ctx.feedback)
        if not feedback and pending.get("key") == key and pending.get("feedback") and not ctx.regenerate:
            feedback = list(pending["feedback"])  # (the change requests the question was about: consumed by the run that asked)
        update = bool(feedback) and not ctx.regenerate and prev.get("key") == key and self.rtl_f_filelist(engine).is_file()
        # (a fresh copy before the plan: the plan reads the copies in eco/rtl/, the ORG RTL may be outside the project)
        mapping = prev.get("map") if update else self._fresh_copy(engine)
        change = await self._decide(ctx, key, feedback, update, req, mapping)
        if change is None:
            return  # (waiting for your answer)
        if update and change.strip().lower().startswith("no rtl change"):
            # (a dv / Sanity request the plan judged not the ECO's to fix: RTL(F) stays; eco_verify reports it instead of looping)
            self.write(engine, RTL_JSON, {**prev, "declined": [*prev.get("declined", []), {"requests": feedback, "why": change}]})
            self.artifact(engine, PLAN_JSON).unlink(missing_ok=True)
            ctx.emit("warning", message=f"RTL(F) kept as it is: {change[:300]}")
            return
        task = [f"## The requirement ({project.rel(req)})", req.read_text(errors="replace"), "", *self._spec_part(engine),
                f"## RTL(F): edit these files in place (top `{self.top(engine)}`; each is a copy of the ORG file named after it)",
                *[f"- {f} (ORG: {o})" for f, o in mapping.items()]]
        if update:
            task += ["", "## Change requests on the current RTL(F)", *[f"- {x}" for x in feedback],
                     "", f"The changes made so far against the ORG RTL are in {project.rel(self.rtl_diff(engine))}."]
        task += ["", "## The change to make (planned, and decided with the user when it differs from the request)", change,
                 "Make this change and nothing more."]
        out = await self._edit(ctx, "\n".join(task))
        problems = self._check(engine)
        if problems:  # one round back to the LLM with the parser's errors
            out = await self._edit(ctx, "\n".join([*task, "", "## RTL(F) does not parse — fix these errors (only them)", *problems[:20]]))
            problems = self._check(engine)
            if problems:
                raise StepFailed("RTL(F) does not parse: " + "; ".join(problems[:5]))
        pairs = [(project.root / o, project.root / f) for f, o in mapping.items()]
        diff = unified_diff(project, pairs)
        old = self.rtl_diff(engine).read_text(errors="replace") if update and self.rtl_diff(engine).is_file() else None
        if old is not None and old == diff:
            # (the same RTL(F): the patch, Post NETLIST and EQ(2) would not run again, the fix loop would stall on the old result)
            raise StepFailed(f"the revised RTL(F) is the same as before ({out.summary[:200]}): fix eco/rtl/ by hand or give eco_rtl another hint")
        self.rtl_diff(engine).write_text(diff)
        if not diff:
            raise StepFailed(f"RTL(F) is the ORG RTL: no change made for the requirement ({out.summary[:300]})")
        self.write(engine, RTL_JSON, {"key": key, "map": mapping, "summary": out.summary, "changes": [c.model_dump() for c in out.changes],
                                      "concerns": out.concerns, "diff_lines": diff.count("\n"), "change": change})
        self.artifact(engine, PLAN_JSON).unlink(missing_ok=True)  # (done: the next request is planned again)
        ctx.emit("log", message=f"RTL(F): {out.summary[:200]} ({len(out.changes)} file(s), see {project.rel(self.rtl_diff(engine))})")
        for c in out.concerns:
            ctx.emit("warning", message=f"RTL(F): {c}")

    async def _decide(self, ctx: StepContext, key: dict, feedback: list[str], update: bool, req: Path, mapping: dict) -> str | None:
        """The change to make: the plan's, or — when the request prescribes a way and a smaller change exists — your choice (None while
        your answer is awaited). The plan and the request are kept in PLAN_JSON until the change is made."""
        engine, project = ctx.engine, ctx.project
        qkey = sha256_json({"key": key, "feedback": feedback})[:16]
        pending = self.read(engine, PLAN_JSON, {}) or {}
        if pending.get("qkey") != qkey:
            task = [f"## The requirement ({project.rel(req)})", req.read_text(errors="replace"), "", *self._spec_part(engine),
                    f"## The RTL to change (top `{self.top(engine)}`; " + ("the current RTL(F)" if update else "copies of the ORG RTL") + ")",
                    *[f"- {f}" for f in mapping]]
            if update:
                task += ["", "## Change requests on this RTL(F)", *[f"- {x}" for x in feedback],
                         f"(The changes made so far against the ORG RTL: {project.rel(self.rtl_diff(engine))}.)"]
            stage = Stage(name="eco_rtl_plan", system_prompt=SYSTEM["PLAN"], prompt="\n".join(task), cwd=project.root,
                          builtin_tools=["Read", "Grep", "Glob"], output_model=RtlPlan,
                          deny_dirs=self._denied(engine))
            plan: RtlPlan = (await ctx.llm(stage)).output
            pending = {"qkey": qkey, "key": key, "feedback": feedback, **plan.model_dump()}
            self.write(engine, PLAN_JSON, pending)
        alt = pending.get("alternative")
        if not alt:
            return pending["plan"]
        asked = pending.get("requested") or "the change as the requirement / change request describes it"
        qid, answer = self.decide(ctx, f"alt:{qkey}", "ECORTL", (
            f"RTL(F): the request asks for {asked}. A smaller change gives the same required function: {alt['change']} — smaller because "
            f"{alt['smaller_because']}; same function because {alt['same_function_because']}. It differs from the request: "
            f"{alt['differs_from_request']}. Which change should RTL(F) make?"),
            [(f"{USE_ALT} (Recommended): {alt['change']}", "fewer netlist edits; the requirement's function is kept"),
             (f"{KEEP}: {asked}", "exactly what was asked"),
             (f"{OWN}: <type how to change it>", "your words go to the RTL edit")])
        if answer is None:
            ctx.emit("warning", message=f"RTL(F): a smaller change than the one asked exists — answer {qid} (see schemas/{PLAN_JSON})")
            return None
        pending["decision"] = {"question": qid, "answer": answer}
        self.write(engine, PLAN_JSON, pending)
        ctx.emit("log", message=f"RTL(F): {qid or 'auto-answer'} → {answer[:120]}")
        return chosen_change(answer, pending)

    async def _edit(self, ctx: StepContext, task: str) -> RtlUpdate:
        engine, project = ctx.engine, ctx.project
        stage = Stage(name="eco_rtl", system_prompt=SYSTEM["RTL"], prompt=task, cwd=project.root,
                      builtin_tools=["Read", "Grep", "Glob", "Edit", "Write"], output_model=RtlUpdate,
                      write_dirs=[self.rtl_f_dir(engine)],
                      deny_dirs=self._denied(engine))
        return (await ctx.llm(stage)).output

    def _denied(self, engine) -> list[Path]:
        project, eco = engine.project, self.eco_dir(engine)
        return [project.build_dir, self.org_dir(engine), eco / "org", eco / "netlist", eco / "patch", project.src_dir / "tb", project.tb_dir]

    def _spec_part(self, engine) -> list[str]:
        """Project mode: the spec update the RTL follows (eco_spec), as a diff against the ORG spec."""
        d = self.spec_diff(engine)
        if self.mode(engine) != "project" or not d.is_file() or not d.read_text().strip():
            return []
        return [f"## The spec update of this ECO ({engine.project.rel(d)}, against the ORG spec in ref/)", d.read_text(errors="replace"), ""]

    def _check(self, engine) -> list[str]:
        """The parse errors RTL(F) has and the ORG RTL has not (an error of the ORG RTL — e.g. `unknown module` of a hard macro that has
        only a .db — is not the change's: it was synthesized that way)."""
        from collections import Counter
        from q3tui.hdl.filelist import parse_filelist
        from q3tui.hdl.parse import parse_design
        root, top = engine.project.root, self.top(engine)

        def errors(filelist: Path) -> list:
            return parse_design(parse_filelist(filelist, root), top).errors

        def key(d) -> tuple[str, str]:  # (the file's name and the message: lines move in an edited file, copies may be renamed)
            return (Path(getattr(d, "file", None) or "").name, d.message)

        new = errors(self.rtl_f_filelist(engine))
        known = Counter(key(d) for d in errors(self.org_filelist(engine))) if new else Counter()
        out = []
        for d in new:
            if known[key(d)] > 0:
                known[key(d)] -= 1
                continue
            out.append(f"{d.file}:{d.line}: {d.message}" if getattr(d, "file", None) else d.message)
        return out
