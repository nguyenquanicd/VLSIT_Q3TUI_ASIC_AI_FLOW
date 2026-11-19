"""ECO step `eco_rtl`: RTL(F), the RTL changed to the requirement with the smallest change in the netlist first, then in the RTL. Its tasks
(one file each, `tasks/<task>.py`; an LLM task's prompt `tasks/<task>.md`):

- plan (LLM, read-only): the smallest change found in the ORG netlist itself (fewest new cells, existing nets reused, at the register /
  output where it acts — no guess of what a new synthesis would make), as Design Compiler netlist edits, and the RTL change that mirrors
  them (`schemas/eco_rtl_plan.json`). Code checks the edits against the netlist (`edits.checked`: named from the top, allowed commands,
  cells / nets that exist) — refused ones go back to the plan once; the checked edits go on to eco_patch (`schemas/eco_rtl.json`);
- decide: when the requirement or a change request prescribes a way and the plan finds a cheaper one with the same required function, you
  are asked (blocking): the cheaper change (recommended; auto-answer takes it), the change as asked, or your own words;
- hand-off (project mode, RTL the rtl flow made): the planned change goes to the rtl flow's `rtl` step as one change request per module
  (`[rtl:<module>]`), and the rtl flow runs (it edits src/rtl, lints and smoke-tests; its gate and questions are its own: when it stops there,
  this step fails until you finished there and run eco again — the request is not sent twice);
- edit (external mode: a copy of the ORG RTL in `eco/rtl/`; or RTL that is your own, not the rtl flow's): code applies the plan's exact
  RTL edits (`rtl_edits`: old → new, no LLM rewrites them); an LLM stage edits RTL(F) only for a change you chose in other words, or when
  an edit does not fit the file;
- check: RTL(F) parsed (pyslang; an edit's error goes back to the LLM once) and `eco/rtl.diff` written against the ORG RTL.

A change request (your review, EQ(2), dv / Sanity, eco_patch's netlist cost) is planned the same way on the current RTL(F); a changed
requirement or ORG RTL starts again from the ORG RTL (ref/)."""
from __future__ import annotations

import shutil
from pathlib import Path

from q3tui.core.project import sha256_file, sha256_json
from q3tui.flows.eco.eco_rtl.tasks import check, decide, edit, hand_off, plan
from q3tui.flows.eco.eco_rtl.tasks.plan import PLAN_JSON
from q3tui.flows.eco.lib.base import EQ1_JSON, INPUTS_JSON, RTL_JSON, SPEC_JSON, EcoStep
from q3tui.pipeline.base import StepContext


def copy_names(files: list[Path]) -> dict[Path, str]:
    """The name of each ORG file in eco/rtl/: its own, or `<parent>__<name>` when two files share a name."""
    seen: dict[str, int] = {}
    for f in files:
        seen[f.name] = seen.get(f.name, 0) + 1
    return {f: (f.name if seen[f.name] == 1 else f"{f.parent.name}__{f.name}") for f in files}


class Step(EcoStep):
    name = "eco_rtl"
    title = "RTL(F): the RTL updated to the requirement"
    deps = ("eco_spec",)
    tasks = (plan.TASK, decide.TASK, hand_off.TASK, edit.TASK, check.TASK)

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

    def _fresh_copy(self, engine, copy: bool = True) -> dict[str, str]:
        """eco/rtl/ = the ORG RTL again, with a filelist of the copies (the ORG include dirs and defines kept). {copy: ORG file}.
        Project mode: the project's RTL files are the ORG ones again (from ref/; the filelist is the project's own). {RTL file: ref copy}
        (`copy` False: only the map — the rtl flow already made the change on the ORG RTL)."""
        from q3tui.hdl.filelist import parse_filelist
        project = engine.project
        if self.mode(engine) == "project":
            ref = self.ref_dir(engine)
            mapping = {}
            for org in self.org_rtl_files(engine):
                dst = project.root / org.relative_to(ref)
                if copy and (not dst.is_file() or dst.read_bytes() != org.read_bytes()):
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
        asks, answered, open_ = self.concern_answers(ctx, prev, key)
        if answered:  # (your answers to the concerns: change requests from now on, kept in the plan if it asks first)
            self.write(engine, RTL_JSON, {**prev, "concern_asks": asks})
        feedback = [*ctx.feedback, *answered]
        if not feedback and pending.get("key") == key and pending.get("feedback") and not ctx.regenerate:
            feedback = list(pending["feedback"])  # (the change requests the question was about: consumed by the run that asked)
        if asks and not feedback and not ctx.regenerate:  # (a run for your answers to the concerns: each one kept, or still open)
            self.write(engine, RTL_JSON, {**prev, "concern_asks": asks})
            ctx.emit("warning" if open_ else "log", message=f"RTL(F): answer {', '.join(open_)} (the concerns of the change), then run again"
                     if open_ else "RTL(F): every concern answered — the change is kept")
            return
        update = bool(feedback) and not ctx.regenerate and prev.get("key") == key and self.rtl_f_filelist(engine).is_file()
        qkey = sha256_json({"key": key, "feedback": feedback})[:16]
        # (handed off already — this run comes after you finished in the rtl flow: src/rtl holds its change, never the ORG RTL again)
        handed = engine.state.step_meta.get(self.name, {}).get("handed") == qkey and not ctx.regenerate
        # (a fresh copy before the plan: the plan reads the copies in eco/rtl/, the ORG RTL may be outside the project)
        mapping = prev.get("map") if update else self._fresh_copy(engine, copy=not handed)
        pending = await plan.run(self, ctx, key, feedback, update, req, mapping, qkey)
        change = decide.run(self, ctx, pending, qkey)
        if change is None:
            return  # (waiting for your answer)
        if update and change.strip().lower().startswith("no rtl change"):
            # (a dv / Sanity request the plan judged not the ECO's to fix: RTL(F) stays; eco_verify reports it instead of looping)
            self.write(engine, RTL_JSON, {**prev, "concern_asks": asks,
                                          "declined": [*prev.get("declined", []), {"requests": feedback, "why": change}]})
            self.artifact(engine, PLAN_JSON).unlink(missing_ok=True)
            self.task(ctx, "check", f"RTL(F) kept as it is: {change}", "skipped")
            ctx.emit("warning", message=f"RTL(F) kept as it is: {change[:300]}")
            return
        planned = self.read(engine, PLAN_JSON, {}) or {}
        modules = list(planned.get("modules") or [])
        owner = hand_off.owner_modules(self, engine, modules)
        exact = list(planned.get("rtl_edits") or []) if change == planned.get("plan") else []  # (the plan's own change, not your other way)
        if owner:
            out = await hand_off.run(self, ctx, change + ("\n\nThe exact edits:\n" + plan.edits_text(exact) if exact else ""), owner, qkey)
            self.task(ctx, "edit", "not needed: the rtl flow made the change", "skipped")
        else:
            self.task(ctx, "hand-off", "external mode" if self.mode(engine) != "project" else
                      f"not the rtl flow's RTL ({', '.join(modules) or 'no module named'}): edited here", "skipped")
            out = await edit.run(self, ctx, req, mapping, feedback, update, change, exact)
        check.run(self, ctx, out, key=key, mapping=mapping, update=update, change=change, owner=owner, planned=planned, asks=asks)
