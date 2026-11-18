"""ECO step `eco_inputs`: which ORG RTL (a filelist), ORG netlist and requirement the ECO works on. Paths set in the step's options are used as
they are; otherwise the step asks you: the defaults (what the asic flow leaves) or your own paths. The mode follows from the RTL: the project's
own `src/rtl` is `project` mode (the ECO updates the spec and the RTL in place, dv / Sanity may run again), any other filelist `external`
(fire-fighting). The ORG design is kept in `ref/<name>/` (you are asked the name; lib/ref.py), the netlist with its `.sdc` / `.svf` in
`ref/<name>/netlist/`; `schemas/eco_inputs.json` records the choice, the mode, the ref and the files' hashes."""
from __future__ import annotations

import re
from pathlib import Path

from q3tui.core.project import sha256_file
from q3tui.flows.eco.lib import ref as refmod
from q3tui.flows.eco.lib.base import DEFAULTS, INPUTS_JSON, EcoStep, answer_is
from q3tui.pipeline.base import StepContext, StepFailed

KEYS = ("rtl", "netlist", "requirement")
USE_DEFAULTS = "Use the defaults"
OWN_PATHS = "My own paths: rtl=<filelist.f> netlist=<netlist.v> requirement=<file.md>"
REQUIREMENT_STUB = """# ECO requirement

Write here what the ECO must change in the design: the behaviour wanted, the signals / modules concerned, and how to check it.
"""


def parse_paths(text: str) -> dict[str, str]:
    """`rtl=… netlist=… requirement=…` (spaces, commas or semicolons between them) from your answer."""
    return {k.lower(): v.strip().strip("\"'") for k, v in re.findall(r"\b(rtl|netlist|requirement)\s*[=:]\s*(\"[^\"]+\"|'[^']+'|[^\s,;]+)", text, re.I)}


class Step(EcoStep):
    name = "eco_inputs"
    title = "ECO inputs"
    hashed_options = ("rtl", "netlist", "requirement", "top", "ref_name")

    def _chosen(self, engine) -> tuple[dict[str, str] | None, str]:
        """(the three paths, how they were chosen), or (None, "") while your answer is awaited."""
        top = self.top(engine) or "top"
        defaults = {k: v.format(top=top) for k, v in DEFAULTS.items()}
        given = {k: str(self.options[k]) for k in KEYS if self.options.get(k)}
        if given:
            return {**defaults, **given}, "options"
        qid = next((q.id for q in self.questions_list(engine)), None)
        answer = self.answers(engine).get(qid) if qid else None
        if answer is None:
            return None, ""
        if answer_is(answer, USE_DEFAULTS, "default", "yes", "mặc định"):
            return defaults, "defaults"
        paths = parse_paths(answer)
        if not paths:
            raise StepFailed(f"{qid}: give the paths as `rtl=<filelist.f> netlist=<netlist.v> requirement=<file.md>` (or answer "
                             f"\"{USE_DEFAULTS}\")")
        return {**defaults, **paths}, "your paths"

    def inputs(self, engine) -> list[Path]:
        chosen, _ = self._chosen_quiet(engine)
        files = [engine.project.root / p for p in (chosen or {}).values()]
        if chosen:  # (the .sdc / .svf beside the netlist are copied too)
            net = engine.project.root / chosen["netlist"]
            files += [net.with_suffix(".sdc"), net.with_suffix(".svf")]
        return [self._q_paths(engine)[1], *[f for f in files if f.is_file()]]

    def _chosen_quiet(self, engine):
        try:
            return self._chosen(engine)
        except StepFailed:
            return None, ""

    def outputs(self, engine) -> list[Path]:
        # (not eco/ref.json: a reset deletes a step's outputs, and the pointer must outlive it)
        return [x for x in (self.artifact(engine, INPUTS_JSON),) if x.is_file()]

    def reset_files(self, engine) -> list[Path]:
        # (never eco/ref.json nor ref/: a reset must not snapshot again a project the ECO already changed)
        return [x for x in (self.artifact(engine, INPUTS_JSON), *self._q_paths(engine)) if x.is_file()]

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        top = self.top(engine)
        if not top:
            raise StepFailed("no top module: set `top` of eco_inputs (Settings, or q3tui.yaml step_options.eco_inputs.top)")
        chosen, how = self._chosen(engine)
        if chosen is None:
            qid, answer = self.decide(ctx, "source", "ECOIN", (
                "Which inputs should the ECO use? The defaults are the asic flow's: ORG RTL `" + DEFAULTS["rtl"] + "`, ORG netlist `"
                + DEFAULTS["netlist"].format(top=top) + "`, requirement `" + DEFAULTS["requirement"] + "`. Or give your own paths."),
                [(USE_DEFAULTS, "the asic flow's RTL filelist and netlist, the requirement in eco/requirement.md"),
                 (OWN_PATHS, "answer with the three paths (project-relative or absolute)")])
            if answer is None:
                ctx.emit("warning", message=f"ECO inputs: answer {qid} (defaults or your paths), then run again")
                return
            chosen, how = {k: v.format(top=top) for k, v in DEFAULTS.items()}, "defaults"  # (auto-answer: the first option)
        root = project.root
        req = root / chosen["requirement"]
        if not req.is_file() and how != "your paths":
            req.parent.mkdir(parents=True, exist_ok=True)
            req.write_text(REQUIREMENT_STUB)
            raise StepFailed(f"write the ECO requirement in {project.rel(req)} (a template is there now), then run again")
        missing = [f"{k}: {chosen[k]}" for k in KEYS if not (root / chosen[k]).is_file()]
        if missing:
            raise StepFailed("ECO input not found — " + "; ".join(missing) + (" (run the asic flow first for its netlist)" if how == "defaults" else ""))
        net, fl = (root / chosen["netlist"]).resolve(), (root / chosen["rtl"]).resolve()
        mode = refmod.mode_of(project, fl)
        rec = refmod.pointer(project)
        if not (rec and rec.get("sources") == {"rtl": str(fl), "netlist": str(net)} and (root / rec.get("path", "-")).is_dir()):
            name = self._ref_name(ctx, top)
            if name is None:
                return
            from q3tui.hdl.filelist import parse_filelist
            d = refmod.unique_dir(project, name)
            try:
                rec = refmod.snapshot(project, d, mode, fl, parse_filelist(fl, root).files, net, top)
            except FileNotFoundError as exc:
                raise StepFailed(str(exc)) from exc
            refmod.save_pointer(project, rec)
            ctx.emit("log", message=f"ECO ref: the ORG design kept in {rec['path']} ({mode} mode)")
        else:
            ctx.emit("log", message=f"ECO ref: {rec['path']} (kept from {rec.get('created')}; delete eco/ref.json to start a new ECO)")
        mode, ref = rec["mode"], root / rec["path"]
        rel = {k: (project.rel(root / v) if (root / v).resolve().is_relative_to(root.resolve()) else str(root / v)) for k, v in chosen.items()}
        org = ref / "netlist" / f"{top}.v"
        self.write(engine, INPUTS_JSON, {"top": top, "mode": mode, "ref": rec["path"], "source": {k: rel[k] for k in ("rtl", "netlist")},
                                         "rtl": project.rel(ref / refmod.RTL_FILELIST), "netlist": project.rel(org),
                                         "requirement": rel["requirement"], "how": how, "org_netlist": project.rel(org),
                                         "org_sdc": project.rel(org.with_suffix(".sdc")) if org.with_suffix(".sdc").is_file() else None,
                                         "org_svf": project.rel(org.with_suffix(".svf")) if org.with_suffix(".svf").is_file() else None,
                                         "sha256": {k: sha256_file(root / v) for k, v in chosen.items()}})
        ctx.emit("log", message=f"ECO inputs ({how}, {mode} mode): RTL {rel['rtl']}, netlist {rel['netlist']}, requirement {rel['requirement']}"
                                + ("" if mode == "project" else " — a fire-fighting ECO: no spec update, no dv / Sanity run"))

    def _ref_name(self, ctx: StepContext, top: str) -> str | None:
        """The folder name of ref/: the `ref_name` option, else your answer (default: the top module); None while it is awaited."""
        if self.options.get("ref_name"):
            return refmod.clean_name(str(self.options["ref_name"]))
        qid, answer = self.decide(ctx, "ref", "ECOREF", (
            f"Where should the ECO keep the ORG design (the un-ECO'd RTL and netlist; for the project's own RTL also spec/, src/, "
            f"constraints/, schemas/)? It goes to ref/<name>/ "
            f"(ref/<name>_DDMMYYYY_HHMMSS when that folder exists already)."),
            [(f"ref/{top} (Recommended)", "named after the top module"), ("My own name: name=<folder>", "answer with the folder name")])
        if answer is None:
            ctx.emit("warning", message=f"ECO ref: answer {qid} (the name of the ref/ folder), then run again")
            return None
        if answer_is(answer, f"ref/{top}", "use the default", "default", "yes", "mặc định") or ("=" in answer and not re.search(r"name\s*[=:]", answer)):
            return top  # (an answer that is not a name, e.g. the paths given to the other question: the default)
        return refmod.clean_name(answer)
