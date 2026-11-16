"""ASIC step `asic_macro`: the memory wrappers of the RTL as memory macros of the PDK (`schemas/asic_macro.json`, the ASIC bodies in
`build/syn/asic/macros/`). It runs after the SDC: the clock period decides which macros are fast enough (the Liberty `minimum_period` of
the clock pin) and goes to a memory compiler that takes one.

Per wrapper (`*_sram` / `*_rf` / `*_rom`): what it is (`MemSpec`: words, bits, its ports — a small read-only LLM stage, checked by code
against the elaborated ports), then the source:
1. a memory compiler of the PDK (code finds the executables; an LLM stage reads the kit and judges it). It runs only as the tool role
   `mem_compile` of config/tools.json: without that role the step says what the compiler needs (the stage's proposal) and goes on with
2. the pre-generated macros: every memory Liberty file of the PDK's memory folders (code), the smallest rows × columns of one macro that
   has the ports, the write mask and the clock (code), the pins of the macro family from an LLM stage (`PinMap`, checked by code).
3. none fits (more read ports than any macro, a read latency other than 1, `options.flops`): flip-flops, said so.
The ASIC body is written by code; the macros' `.lib` become `.db` (tool role `lib_compile`, Library Compiler); the body is checked against
the behavioural wrapper in lock-step (tool roles `sim` + `run`; N/A without them). `asic_synth` and `asic_lec` take the bodies in place of
the behavioural files and the `.db` in their link libraries. Changes propagate as updates: a wrapper whose text, corner, clock and options
did not change keeps its macro (no LLM, no tool)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anyio

from q3tui.eda import tools as toolmod
from q3tui.flows import skill_sections
from q3tui.flows.asic.lib import macro
from q3tui.flows.asic.lib.base import AsicStep
from q3tui.flows.fpga.lib import sdc as sdcmod
from q3tui.llm.runtime import Stage
from q3tui.pipeline.base import StepContext, StepFailed
from q3tui.steps.common import Question, QuestionOption, StepQuestions, assign_question_ids, load_answers

SYSTEM = skill_sections(Path(__file__).parent / "md" / "skill.md")


def _sha(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


KEEP = "keep flip-flops"
CHANGE = "change the design"


def choice(answer: str | None) -> str:
    """What an answer to a macro question says: "use" (the macro the check rejected), "keep" (flip-flops), "change" (any other text:
    a change of the design), or "" (not answered)."""
    a = (answer or "").strip().lower()
    return "" if not a else "use" if a.startswith("use ") else "keep" if a.startswith("keep") else "change"


NO_PDK = "no PDK folder to look in (options.pdk_root, or a library under a PDK with a MEMORY / SRAM folder)"


class Step(StepQuestions, AsicStep):
    name = "asic_macro"
    title = "ASIC memory macros"
    deps = ("sdc", "asic_port")
    tool_roles = ("lib_compile",)
    hashed_options = ("pdk_root", "corner", "prefer", "flops")  # (staleness: these change the result)

    def macro_dir(self, engine) -> Path:
        return self.asic_dir(engine) / "macros"

    def inputs(self, engine) -> list[Path]:  # (an answer is an input: it makes the step run again)
        return [self.filelist(engine), *self.rtl_files(engine), sdcmod.config_path(engine.project), self._q_paths(engine)[1]]

    def outputs(self, engine) -> list[Path]:
        p = self.artifact(engine, macro.MACRO_JSON)
        files = [engine.project.root / w["asic_file"] for w in (self.read(engine, macro.MACRO_JSON, {}) or {}).get("wrappers", {}).values() if w.get("asic_file")]
        return [x for x in (p, *files) if x.is_file()]

    def reset_files(self, engine) -> list[Path]:
        return [*self.outputs(engine), *(p for p in self._q_paths(engine) if p.is_file())]

    def missing_input(self, engine) -> str | None:
        return self.missing_rtl(engine)

    # -- pieces ------------------------------------------------------------------------------------------------------------

    def _period(self, project) -> float | None:
        """The clock the macros must meet: the fastest clock of the SDC at its ASIC frequency (shortcut: every wrapper on the fastest clock;
        per-wrapper clocks when a design has a slow memory clock)."""
        cfg = sdcmod.load(project)
        periods = [1000.0 / c.asic_freq_mhz if c.asic_freq_mhz else c.period_ns for c in (cfg.clocks if cfg else [])]
        return min(periods) if periods else None

    def _ports(self, engine, names: list[str]) -> dict[str, dict[str, tuple[str, int]]]:
        """{wrapper: {port: (direction, width)}} as elaborated in the design (the parent's parameters)."""
        from q3tui.hdl.filelist import parse_filelist
        from q3tui.hdl.parse import parse_design

        design = parse_design(parse_filelist(self.filelist(engine), engine.project.root), self.top(engine))
        return {n: {p.name: (p.direction, macro.width(p.type)) for p in design.modules[n].ports} for n in names if n in design.modules}

    def _stage(self, ctx: StepContext, name: str, prompt: str, model, add_dirs: list[Path] = ()) -> Stage:
        project = ctx.project
        return Stage(name=name, system_prompt=SYSTEM[name.removeprefix("asic_macro_").upper()], prompt=prompt, cwd=project.root,
                     builtin_tools=["Read", "Grep", "Glob"], output_model=model, add_dirs=list(add_dirs), max_turns=30,
                     deny_dirs=[project.src_dir / "tb", project.src_dir / "sva", project.tb_dir, project.model_dir, project.build_dir])

    async def _spec(self, ctx, module: str, file: Path, ports: dict) -> macro.MemSpec:
        rel = ctx.project.rel(file)
        prompt = (f"# The wrapper\n`{module}` in `{rel}` (read it). Its ports as instantiated in the design (ground truth):\n"
                  + "\n".join(f"- {n}: {d} [{w}]" for n, (d, w) in ports.items())
                  + "\n\nDescribe the memory it holds and the ports that reach it.")
        out: macro.MemSpec = (await ctx.llm(self._stage(ctx, "asic_macro_spec", prompt, macro.MemSpec))).output
        return out

    async def _pins(self, ctx, m: macro.Macro, pins: dict) -> macro.PinMap:
        prompt = (f"# The macro\n`{m.name}` ({m.words} x {m.bits}, Liberty `{m.lib}`" + (f", Verilog model `{m.model}`" if m.model else "") + ").\n"
                  "Its pins from the Liberty file (ground truth):\n" + "\n".join(f"- {n}: {d} [{w}]" for n, (d, w) in sorted(pins.items()))
                  + "\n\nRead the model (its header comments and the logic) and map the pins.")
        dirs = list(dict.fromkeys(Path(x).parent for x in (m.lib, m.model) if x))
        return (await ctx.llm(self._stage(ctx, "asic_macro_pins", prompt, macro.PinMap, dirs))).output

    async def _review(self, ctx, root: Path, todo: dict[str, dict], pinmaps: dict) -> macro.Review:
        """The memories that ended up as flip-flops: an LLM judges each reason (a check that is wrong, a real mismatch, or intended)."""
        lines = []
        for m, r in todo.items():
            s = r.get("spec") or {}
            lines.append(f"## `{m}` (`{r['file']}`)\n{s.get('words')} x {s.get('bits')}, read latency {s.get('read_latency')}, ports "
                         + ", ".join(f"{p['kind']}" + (" with byte enables" if p.get("be") else "") for p in s.get("ports", []))
                         + f"\nWhy no macro (the code's notes, ground truth of what was rejected): {r.get('why')}")
        fams = [f"- pins `{k}`: map {json.dumps(v.get('map'))[:1500]}; check: {v.get('bad') or 'passed'}" for k, v in pinmaps.items() if v.get("map")]
        prompt = ("# Memories that ended up as flip-flops\n" + "\n\n".join(lines)
                  + ("\n\n# The pin maps of the macro families (kept; checked by code against each macro)\n" + "\n".join(fams) if fams else "")
                  + f"\n\nThe macros are under `{root}` (Liberty and Verilog models: read them where a reason needs it). Judge each wrapper.")
        return (await ctx.llm(self._stage(ctx, "asic_macro_review", prompt, macro.Review, [root]))).output

    async def _compiler(self, ctx, root: Path, exes: list[str], module: str, spec: macro.MemSpec, period: float | None, corner: str) -> macro.CompilerPlan:
        prompt = (f"# The PDK\n`{root}`. Memory compiler executables found there (ground truth):\n" + "\n".join(f"- {e}" for e in exes)
                  + f"\n\n# The memory\n`{module}`: {spec.words} words x {spec.bits} bits, ports "
                  + ", ".join(p.kind + (" with byte enables" if p.be else "") for p in spec.ports)
                  + f", read latency {spec.read_latency}" + (f", clock period {period:g} ns" if period else "") + (f", corner {corner}" if corner else "")
                  + ".\n\nJudge whether a compiler here can make it, and if so how.")
        return (await ctx.llm(self._stage(ctx, "asic_macro_compiler", prompt, macro.CompilerPlan, [root]))).output

    # -- run ---------------------------------------------------------------------------------------------------------------

    async def run(self, ctx: StepContext) -> None:
        engine, project = ctx.engine, ctx.project
        files = self.rtl_files(engine)
        found = macro.wrappers(files)
        prev = self.read(engine, macro.MACRO_JSON, {}) or {}
        out_dir = self.macro_dir(engine)
        if not found:
            self.write(engine, macro.MACRO_JSON, {"wrappers": {}, "pinmaps": prev.get("pinmaps", {})})
            ctx.unchanged = not prev.get("wrappers")
            ctx.emit("log", message="ASIC macros: no memory wrapper (*_sram / *_rf / *_rom) in the RTL — nothing to map")
            return
        answers = load_answers(self._q_paths(engine)[1])
        asks: dict[str, dict] = dict(prev.get("asks") or {})  # {question id: {wrapper, macro, pin_key, request, sent}}
        picked = {q: choice(answers.get(q)) for q in asks}
        self._overrides = {a["pin_key"] for q, a in asks.items() if picked[q] == "use" and a.get("pin_key")}
        keep = {a["wrapper"] for q, a in asks.items() if picked[q] == "keep"}
        self._send_changes(engine, asks, picked, answers)
        libs = self.libraries(engine)
        corner = str(self.options.get("corner") or (macro.corner_of(libs[0]) if libs else ""))
        root_opt = self.options.get("pdk_root")
        root = Path(str(root_opt)).expanduser() if root_opt else (macro.pdk_root(libs[0]) if libs else None)
        period = self._period(project)
        flops = {str(x) for x in self.options.get("flops") or []}
        prefer = str(self.options.get("prefer") or "compiler")
        ports = await anyio.to_thread.run_sync(lambda: self._ports(engine, list(found)))
        catalog: list[macro.Macro] = []
        exes: list[str] = []
        if root and root.is_dir():
            cache = self.workdir(engine) / "catalog.json"
            key = macro.catalog_key(root, corner)
            catalog = macro.load_catalog(cache, key) or []
            if not catalog:
                ctx.emit("log", message=f"ASIC macros: looking for memory macros in {root} (corner {corner or 'any'})…")
                catalog = await anyio.to_thread.run_sync(lambda: macro.scan(root, corner))
                macro.save_catalog(cache, key, catalog)
            exes = await anyio.to_thread.run_sync(lambda: macro.compilers(root))
        pinmaps: dict[str, dict] = dict(prev.get("pinmaps") or {})
        results: dict[str, dict] = {}
        new: list[str] = []  # the wrappers chosen again this run (the others keep their macro and their check)
        compiler_note = prev.get("compiler") or {}
        for module, file in sorted(found.items()):
            text = file.read_text(errors="replace")
            wport = ports.get(module) or {}
            key = _sha(macro.VERSION, text, wport, corner, str(root), period, module in flops, prefer, [m.name for m in catalog][:2000], exes,
                       module in keep, sorted(self._overrides))
            old = (prev.get("wrappers") or {}).get(module) or {}
            if old.get("key") == key and (not old.get("asic_file") or (project.root / old["asic_file"]).is_file()):
                results[module] = old
                continue
            new.append(module)
            res = macro.Result(module, project.rel(file), "flops", key=key, corner=corner)
            results[module] = res.__dict__
            if not wport:
                res.why = "not instantiated in the design (no elaborated ports)"
                continue
            same_text = old.get("spec") and old.get("text") == _sha(text, wport)  # (only the PDK, clock or options changed: the spec stands)
            spec = macro.MemSpec.model_validate(old["spec"]) if same_text else await self._spec(ctx, module, file, wport)
            res.spec = spec.model_dump()
            bad = macro.spec_problems(spec, wport)
            if bad:
                res.why = "; ".join(bad)
            elif module in flops:
                res.why = "options.flops"
            elif module in keep:
                res.why = "flip-flops: your answer"
            elif not root or not root.is_dir():
                res.why = NO_PDK
            else:
                await self._implement(ctx, res, module, spec, wport, text, catalog, exes, root, period, corner, prefer, pinmaps, compiler_note, out_dir)
            results[module] = {**res.__dict__, "text": _sha(text, wport)}
        for gone in set((prev.get("wrappers") or {})) - set(found):  # (a wrapper no longer in the RTL: its body goes)
            f = project.root / ((prev["wrappers"][gone] or {}).get("asic_file") or "")
            if f.is_file() and f.suffix == ".sv":
                project.backup([f])
                f.unlink()
        changed = bool(new) or set(prev.get("wrappers") or {}) != set(found)
        handed = {a["wrapper"] for q, a in asks.items() if picked.get(q) == "change"} - set(new)  # (asked again once the wrapper changed)
        asks = await self._ask(ctx, root, results, new, flops | keep | handed, asks, answers, pinmaps, catalog)
        await self._make_dbs(ctx, results, out_dir)
        await self._check(ctx, results, new, found, ports, out_dir)
        data = {"pdk_root": str(root) if root else None, "corner": corner, "period_ns": period, "catalog": len(catalog), "compilers": exes,
                "compiler": compiler_note, "wrappers": results, "pinmaps": pinmaps, "asks": asks}
        self.write(engine, macro.MACRO_JSON, data)
        ctx.unchanged = not changed and bool(prev)
        mapped = [f"{m} → {r['rows']}x{r['cols']} {r['macro']}" for m, r in results.items() if r.get("asic_file")]
        kept = [f"{m} (flops: {r['why']})" for m, r in results.items() if not r.get("asic_file")]
        ctx.emit("log", message="ASIC macros: " + "; ".join(mapped + kept))
        lost = [m for m, r in results.items() if r.get("why") == NO_PDK]
        if lost:  # (a memory that could be a macro is never passed as flip-flops for want of a PDK: set it, or list it in options.flops)
            raise StepFailed(f"no PDK folder for the memories {', '.join(lost)}: set `library` (Settings → asic_synth) or `pdk_root` "
                             "(Settings → asic_macro), or keep them as flip-flops with options.flops")
        failed = [m for m, r in results.items() if (r.get("check") or {}).get("status") == "fail"]
        if failed:
            raise StepFailed(f"the ASIC body of {', '.join(failed)} differs from the behavioural wrapper in the lock-step check (build/syn/asic/macros/check/)")

    async def _ask(self, ctx, root, results: dict, new: list[str], settled: set[str], asks: dict, answers: dict, pinmaps: dict,
                   catalog: list) -> dict:
        """Questions for the large memories that ended up as flip-flops (an LLM stage judges why); answered questions stay as decisions.
        Returns the asks to keep."""
        engine = ctx.engine
        def big(r):
            s = r.get("spec") or {}
            return (s.get("words") or 0) * (s.get("bits") or 0) // 8 >= macro.REVIEW_BYTES
        todo = {m: r for m, r in results.items() if r.get("how") == "flops" and r.get("spec") and big(r) and m not in settled and r.get("why") != NO_PDK}
        qs = self.questions_list(engine)
        kept = [q for q in qs if q.id in answers]
        still = [q for q in qs if q.id not in answers and (asks.get(q.id) or {}).get("wrapper") in todo and asks[q.id]["wrapper"] not in new]
        review = {m: r for m, r in todo.items() if m not in {asks[q.id]["wrapper"] for q in still} and (m in new or not r.get("review"))}
        fresh: list[tuple[Question, dict]] = []
        if review:
            out = await self._review(ctx, root, review, pinmaps)
            for v in out.verdicts:
                if v.wrapper not in review:
                    continue
                results[v.wrapper]["review"] = {"kind": v.kind, "explanation": v.explanation}  # (kept with the wrapper: not judged again until it changes)
                if v.kind == "intended":
                    ctx.emit("log", message=f"ASIC macros: {v.wrapper} stays flip-flops — {v.explanation}")
                    continue
                s = review[v.wrapper]["spec"]
                opts = [QuestionOption(label=KEEP, description="the memory is built from flip-flops", impact="area: much larger; timing and power worse")]
                meta = {"wrapper": v.wrapper, "macro": "", "pin_key": "", "request": v.request}
                m = next((x for x in catalog if x.name == v.macro), None) if v.kind == "check_wrong" and v.macro else None
                if m is not None:
                    meta.update(macro=m.name, pin_key=macro.pin_key(macro.lib_pins(Path(m.lib).read_text(errors="replace"))))
                    opts.insert(0, QuestionOption(label=f"use {m.name} anyway", description="the check is wrong: the macro is used; the lock-step check still has to pass",
                                                  impact="area: the macro's; timing: the macro's"))
                if v.request:
                    opts.append(QuestionOption(label=CHANGE, description=f"handed to the spec: {v.request[:200]}", impact="complexity: a spec and RTL update"))
                q = Question(id="", blocking=True, kind="design_choice", default_assumption=opts[0].label, options=opts,
                             question=f"`{v.wrapper}` ({s['words']} x {s['bits']}) became flip-flops. {v.explanation} What should it be?")
                fresh.append((q, meta))
        numbered = assign_question_ids([q for q, _ in fresh], [*kept, *still], "MAC", taken=set(answers))
        out_asks = {q.id: asks[q.id] for q in [*kept, *still] if q.id in asks}
        out_asks.update({q.id: meta for q, (_, meta) in zip(numbered, fresh)})
        self.save_questions(engine, [*kept, *still, *numbered])
        self.write_questions_file(engine)
        if numbered:
            ctx.emit("warning", message="ASIC macros: " + "; ".join(f"{q.id}: {q.question[:120]}" for q in numbered) + " — answer in the step's questions")
        return out_asks

    def _send_changes(self, engine, asks: dict, picked: dict, answers: dict) -> None:
        """An answer that changes the design goes once to the spec step of the flow that owns the RTL (the ASIC port's hand-off flow)."""
        from datetime import datetime

        from q3tui import flows
        from q3tui.pipeline.engine import Engine

        todo = {q: a for q, a in asks.items() if picked.get(q) == "change" and not a.get("sent")}
        if not todo:
            return
        port_step = next((s for s in engine.steps if s.kind == "asic.asic_port"), None)
        owner = flows.load_flow(str((port_step.options if port_step else {}).get("handoff_flow") or "rtl"), engine.project.root)
        other = Engine(engine.project, flow=owner)
        for q, a in todo.items():
            text = answers[q].strip()
            req = a.get("request") if text.lower() == CHANGE else text
            other.request_change("spec", f"ASIC macros ({q}): the memory wrapper `{a['wrapper']}` cannot be a macro as it is. {req}")
            a["sent"] = {"flow": owner.name, "step": "spec", "at": datetime.now().isoformat(timespec="seconds")}

    async def _implement(self, ctx, res, module, spec, wport, text, catalog, exes, root, period, corner, prefer, pinmaps, compiler_note, out_dir) -> None:
        """The source for one wrapper: a compiled macro when the compiler role is there; when it cannot be made or used (the compiler failed,
        its pins, ports or clock do not fit), the smallest fitting tiling of the pre-generated macros."""
        engine, project = ctx.engine, ctx.project
        choice: tuple[macro.Tiling, macro.PinMap] | None = None
        notes: list[str] = []
        sources = [catalog]  # (tried in order: the compiled macro first, when there is one)
        tools = self.tools(engine)
        role = toolmod.available(tools, "mem_compile")
        if exes and prefer != "macros" and (role or compiler_note.get("exes") != exes):  # (no role: the compiler is judged once, not per wrapper)
            plan = await self._compiler(ctx, root, exes, module, spec, period, corner)
            compiler_note.update({"exes": exes, "usable": plan.usable, "reason": plan.reason, "cmd": plan.cmd})
            if plan.usable and role:
                try:
                    got = await self._compile(ctx, module, plan, out_dir)
                except Exception as exc:  # noqa: BLE001 - a broken compiler command: the pre-generated macros
                    got = None
                    ctx.emit("warning", message=f"ASIC macros: {module}: the memory compiler did not run ({exc}) — using the pre-generated macros")
                if got is not None:
                    sources.insert(0, [got])
            elif plan.usable:
                notes.append(f"a memory compiler can make it, but config/tools.json has no tool role mem_compile (proposed: `{plan.cmd}`)")
                ctx.emit("warning", message=f"ASIC macros: {module}: {notes[-1]} — using the pre-generated macros")
        for cands in sources:
            choice = await self._pick(ctx, spec, cands, period, pinmaps, notes)
            if choice is not None:
                res.how = "compiled" if cands is not catalog else "macros"
                break
            if cands is not catalog:
                ctx.emit("warning", message=f"ASIC macros: {module}: the compiled macro does not fit ({'; '.join(notes[-2:])}) — using the pre-generated macros")
        if choice is None:
            res.how, res.why = "flops", ("; ".join(notes[:4]) or "no macro of the PDK has these words / bits / ports")
            return
        t, pm = choice
        body = macro.render(module, text, spec, t, pm, wport)
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{module}.sv"
        project.backup([dest])
        dest.write_text(body)
        check = out_dir / "check" / module
        check.mkdir(parents=True, exist_ok=True)
        (check / f"{module}_q3asic.sv").write_text(macro.render(module, text, spec, t, pm, wport, name=f"{module}_q3asic"))
        res.macro, res.rows, res.cols, res.area_um2 = t.macro.name, t.rows, t.cols, round(t.area, 3)
        res.asic_file, res.lib, res.model, res.lef, res.corner = project.rel(dest), t.macro.lib, t.macro.model, t.macro.lef, t.macro.corner
        res.why = "; ".join(notes[:2])
        res.library = t.macro.library

    async def _pick(self, ctx, spec, cands: list, period, pinmaps: dict, notes: list[str]):
        """The smallest tiling of `cands` whose pins, ports and clock fit: (tiling, pin map), or None (why in `notes`)."""
        for t in macro.tilings(spec, cands)[: macro.CANDIDATES]:
            lib_text = await anyio.to_thread.run_sync(lambda t=t: Path(t.macro.lib).read_text(errors="replace"))
            pins = macro.lib_pins(lib_text)
            pk = macro.pin_key(pins)
            entry = pinmaps.get(pk) or {}
            if "ports" in entry:  # (a map kept by version 1: the map itself)
                entry = pinmaps[pk] = {"map": entry}
            if not entry.get("map") and not entry.get("exc"):  # (asked once per family; a map is kept even when it failed the check)
                try:
                    entry = {"map": (await self._pins(ctx, t.macro, pins)).model_dump()}
                except Exception as exc:  # noqa: BLE001 - this family is out; the next candidate is tried
                    entry = {"bad": f"the pin map failed ({exc})", "exc": True}
                pinmaps[pk] = entry
            if entry.get("exc"):
                notes.append(f"{t.macro.name}: {entry['bad'][:160]}")
                continue
            pm = macro.PinMap.model_validate(entry["map"])
            bad = macro.pinmap_problems(pm, pins, t.macro)  # (checked against each macro: a family shares pin names, not widths)
            entry["bad"] = "; ".join(bad)
            if bad and pk in getattr(self, "_overrides", ()):  # (your answer: the check is wrong — the lock-step check still has to pass)
                notes.append(f"{t.macro.name}: pin check overridden by your answer ({entry['bad'][:120]})")
                bad = []
            if bad:
                notes.append(f"{t.macro.name}: {entry['bad'][:160]}")
                continue
            why = macro.fits(spec, pm)
            if why:
                notes.append(f"{t.macro.name}: {why}")
                continue
            if period:
                mp = macro.min_period_ns(lib_text, pm.ports[0].clk)
                if mp and mp > period:
                    notes.append(f"{t.macro.name}: needs {mp:g} ns, the clock is {period:g} ns")
                    continue
            return t, pm
        return None

    async def _compile(self, ctx, module: str, plan: macro.CompilerPlan, out_dir: Path) -> macro.Macro | None:
        """Run the compiler (tool role mem_compile) on the plan's config; the macro it wrote, or None (said why)."""
        tools = self.tools(ctx.engine)
        work = out_dir / "compiled" / module
        work.mkdir(parents=True, exist_ok=True)
        cfg = work / "memory.cfg"
        cfg.write_text(plan.config)
        res = await anyio.to_thread.run_sync(lambda: toolmod.run_role(tools, "mem_compile", work, {"config": cfg, "workdir": work}, log_name="mem_compile.log"))
        libs = sorted(work.glob(plan.lib_glob)) if plan.lib_glob else []
        if not res.ok or not libs:
            ctx.emit("warning", message=f"ASIC macros: {module}: the memory compiler failed or wrote no .lib (log: {res.log_path}) — using the pre-generated macros")
            return None
        h = macro.lib_header(libs[0].read_text(errors="replace"))
        if h is None:
            return None
        v = sorted(work.glob(plan.v_glob)) if plan.v_glob else []
        lef = sorted(work.glob(plan.lef_glob)) if plan.lef_glob else []
        return macro.Macro(h["cell"], str(libs[0]), macro.corner_of(str(libs[0])), macro._words(h["cell"], h["addr_bits"]), h["bits"], h["addr_bits"],
                           h["area"], str(v[0]) if v else "", str(lef[0]) if lef else "", h["library"], h["kind"])

    async def _make_dbs(self, ctx, results: dict, out_dir: Path) -> None:
        """The .db of every macro used (Library Compiler, tool role lib_compile); a .db newer than its .lib is kept."""
        project = ctx.project
        todo: list[tuple[str, str, Path]] = []
        for r in results.values():
            if not r.get("asic_file") or not r.get("lib"):
                continue
            db = out_dir / "db" / f"{Path(r['lib']).stem}.db"
            r["db"] = project.rel(db)
            if not db.is_file() or db.stat().st_mtime < Path(r["lib"]).stat().st_mtime:
                todo.append((r.get("library") or Path(r["lib"]).stem, r["lib"], db))
        todo = list({t[2]: t for t in todo}.values())
        if not todo:
            return
        tools = self.tools(ctx.engine)
        if not toolmod.available(tools, "lib_compile"):
            raise StepFailed("the macros' Liberty files need Library Compiler to become .db files for Design Compiler: add the tool role "
                             "`lib_compile` (lc_shell, module synopsys/libraryCompiler) to config/tools.json (`q3tui tools init` has it)")
        (out_dir / "db").mkdir(parents=True, exist_ok=True)
        script = out_dir / "db" / "lib2db.tcl"
        script.write_text(macro.lc_script(todo))
        ctx.emit("log", message=f"ASIC macros: {len(todo)} Liberty file(s) → .db (Library Compiler)…")
        res = await anyio.to_thread.run_sync(lambda: toolmod.run_role(tools, "lib_compile", out_dir / "db", {"script": script, "workdir": out_dir / "db"}, log_name="lc.log"))
        toolmod.check_broken(res, "lib_compile")
        missing = [str(db) for _n, _l, db in todo if not db.is_file()]
        if not res.ok or missing:
            raise StepFailed(f"Library Compiler did not write {', '.join(Path(m).name for m in missing) or 'the .db files'} (log: {res.log_path})")

    async def _check(self, ctx, results: dict, new: list[str], found: dict, ports: dict, out_dir: Path) -> None:
        """The lock-step check of each new ASIC body against its behavioural wrapper (tool roles sim + run); N/A without a simulator or a model."""
        tools = self.tools(ctx.engine)
        sim_ok = toolmod.available(tools, "sim") and toolmod.available(tools, "run")
        for module in new:
            r = results[module]
            if not r.get("asic_file"):
                continue
            if not sim_ok or not r.get("model"):
                r["check"] = {"status": "n/a", "why": "no simulator (tool roles sim + run)" if not sim_ok else "no Verilog model of the macro"}
                continue
            spec = macro.MemSpec.model_validate(r["spec"])
            work = out_dir / "check" / module
            work.mkdir(parents=True, exist_ok=True)
            asic_name = f"{module}_q3asic"
            asic = work / f"{asic_name}.sv"  # (written with the body: this module alone, renamed)
            tb = work / "q3_memcheck.sv"
            tb.write_text(macro.check_tb(module, asic_name, spec, ports[module]))
            fl = work / "files.f"
            fl.write_text("\n".join(str(x) for x in (found[module], asic, r["model"], tb)) + "\n")
            res = await anyio.to_thread.run_sync(lambda: toolmod.run_role(tools, "sim", work, {"top": "q3_memcheck", "filelist": fl, "workdir": work, "files": [str(fl)],
                                                                                              "extra_args": ""}, log_name="compile.log"))
            if not res.ok:
                r["check"] = {"status": "fail", "why": f"the check did not compile (log: {ctx.project.rel(Path(res.log_path))})"}
                continue
            run = await anyio.to_thread.run_sync(lambda: toolmod.run_role(tools, "run", work, {"workdir": work, "tc": "memcheck", "test": "memcheck", "seed": 1},
                                                                          log_name="run.log"))
            log = Path(run.log_path).read_text(errors="replace") if run.log_path and Path(run.log_path).is_file() else ""
            r["check"] = {**macro.check_result(log), "log": ctx.project.rel(Path(run.log_path)) if run.log_path else None}
