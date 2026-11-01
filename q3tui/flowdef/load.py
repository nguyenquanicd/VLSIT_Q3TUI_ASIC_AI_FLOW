"""Loading a flow: lookup, params and gates in effect, instances, the artifact graph, and every check of
spec/flow.md. Problems are collected, not raised: a flow with problems cannot run, and the TUI lists them."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from q3tui.flowdef import text as T
from q3tui.flowdef.model import Flow, Input, Instance, Output, Param, Problem, Stage, Task

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
GATES = ("manual", "auto", "unattended")
LLM_TOOLS = ("Read", "Grep", "Glob", "Write", "Edit")
VIEW_KINDS = ("document", "files", "sections", "table")
CHECKS = ("exists", "contains", "json", "tool", "code", "run")
PARAM_TYPES = ("str", "int", "float", "bool", "enum", "list", "map", "path")
BUILT_IN_KINDS = ("design_choice",)

COMMON = {"name", "description", "version"}
FLOW_KEYS = COMMON | {"stages", "overrides"}
STAGE_KEYS = COMMON | {"params", "steps"}
STEP_KEYS = COMMON | {"units", "params", "inputs", "assets", "outputs", "tools", "packages", "pass", "gate",
                      "questions", "answers", "handback", "receives", "skills", "llm_tools", "mcp_tools", "write",
                      "tasks"}
KEYS = {
    "stage_step": {"use", "as", "with", "gate", "when"},
    "flow_stage": {"use", "params", "drop"},
    "override": {"gate", "with"},
    "param": {"type", "values", "default", "required", "affects_result", "doc"},
    "input": {"artifact", "path", "required", "hashed", "llm_visible", "doc"},
    "output": {"artifact", "path", "mode", "user_provided", "schema", "excludes", "when", "view", "doc"},
    "view": {"kind", "title", "review", "template", "by", "rows", "id", "columns", "detail", "state"},
    "units": {"name", "from"},
    "tool": {"role", "required", "doc"},
    "package": {"name", "source", "must_contain", "required", "doc"},
    "pass": {"check", "on_fail", "when", "doc"},
    "task": {"name", "output", "to", "per_unit", "when", "doc"},
    "skill": {"name", "description", "license", "compatibility", "allowed-tools", "metadata"},
}


class Lookup:
    """Where flow files are looked up: `<project>/.q3tui/` first, then `$Q3TUI_HOME/`; the first hit wins."""

    def __init__(self, project_q3: Path | None, home: Path):
        self.roots = [r for r in (project_q3, home) if r is not None]

    def folder(self, kind: str, name: str) -> Path | None:
        for root in self.roots:
            p = root / kind / name
            if p.is_dir():
                return p
        return None

    def file(self, rel: str) -> Path | None:
        """A file under templates/, rules/ or knowledge/ (an asset): one file wins over the file of the same path."""
        for root in self.roots:
            p = root / rel
            if p.is_file():
                return p
        return None

    def flows(self) -> list[str]:
        names: set[str] = set()
        for root in self.roots:
            if (root / "flows").is_dir():
                names |= {p.parent.name for p in (root / "flows").glob("*/FLOW.md")}
        return sorted(names)


def _list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def check_value(p: Param, value) -> str | None:
    """Why a value does not fit a param's declaration (None when it fits)."""
    if value is None:
        return None
    ok = {
        "str": isinstance(value, str),
        "path": isinstance(value, str),
        "int": isinstance(value, int) and not isinstance(value, bool),
        "float": isinstance(value, (int, float)) and not isinstance(value, bool),
        "bool": isinstance(value, bool),
        "list": isinstance(value, list),
        "map": isinstance(value, dict),
        "enum": value in (p.values or []),
    }.get(p.type, True)
    if ok:
        return None
    if p.type == "enum":
        return f"`{value}` is not one of {p.values}"
    return f"`{value!r}` is not a {p.type}"


def _hash_tree(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for base in paths:
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        for f in files:
            h.update(str(f.name if base.is_file() else f.relative_to(base)).encode() + b"\0")
            h.update(f.read_bytes() + b"\0")
    return h.hexdigest()


class _Loader:
    def __init__(self, lookup: Lookup, config=None):
        self.lookup = lookup
        self.config = config  # q3tui.config.ConfigLayers or None
        self.problems: list[Problem] = []

    def err(self, where, message: str) -> None:
        self.problems.append(Problem(str(where), message))

    def keys(self, where, data, allowed: set[str], what: str = "") -> None:
        if isinstance(data, dict):
            for k in data:
                if k not in allowed:
                    self.err(where, f"unknown key `{k}`{' in ' + what if what else ''}")

    def common(self, where, meta: dict, folder: str) -> None:
        if meta.get("name") != folder:
            self.err(where, f"`name` is `{meta.get('name')}`, not the folder `{folder}`")
        if not NAME.match(str(meta.get("name", ""))):
            self.err(where, "`name` must be snake_case, at most 64 characters")
        desc = meta.get("description")
        if not desc:
            self.err(where, "`description` is required")
        elif len(str(desc)) > 1024:
            self.err(where, "`description` is longer than 1024 characters")
        if not SEMVER.match(str(meta.get("version", ""))):
            self.err(where, f"`version` `{meta.get('version')}` is not MAJOR.MINOR.PATCH")

    def params(self, where, decls: dict | None) -> dict[str, Param]:
        out: dict[str, Param] = {}
        for name, d in (decls or {}).items():
            if not isinstance(d, dict):
                self.err(where, f"param `{name}` is not a map")
                continue
            self.keys(where, d, KEYS["param"], f"param `{name}`")
            p = Param(name, d.get("type", ""), d.get("values"), d.get("default"), bool(d.get("required", False)),
                      bool(d.get("affects_result", True)), d.get("doc", ""))
            if p.type not in PARAM_TYPES:
                self.err(where, f"param `{name}`: type `{p.type}` is not one of {list(PARAM_TYPES)}")
            if p.type == "enum" and not p.values:
                self.err(where, f"param `{name}`: an enum needs `values`")
            if p.required and "default" in d:
                self.err(where, f"param `{name}`: `required` with a `default`")
            bad = check_value(p, p.default)
            if bad:
                self.err(where, f"param `{name}`: default {bad}")
            out[name] = p
        return out

    def config_params(self, section: str, key: str) -> dict:
        if self.config is None:
            return {}
        entry = getattr(self.config.config, section).get(key)
        return dict(entry.params) if entry is not None else {}

    # -- the flow -------------------------------------------------------------------------------

    def load(self, name: str) -> Flow:
        folder = self.lookup.folder("flows", name)
        if folder is None or not (folder / "FLOW.md").is_file():
            self.err(f"flows/{name}", f"no flow `{name}` (flows: {', '.join(self.lookup.flows()) or 'none'})")
            return Flow(name, "", "", "", [], {}, {}, {}, {}, {}, self.problems)
        fpath = folder / "FLOW.md"
        try:
            meta, body = T.split(fpath)
        except T.FlowFileError as exc:
            self.err(fpath, exc.reason)
            return Flow(name, "", "", "", [], {}, {}, {}, {}, {}, self.problems)
        self.keys(fpath, meta, FLOW_KEYS)
        self.common(fpath, meta, name)
        files = [fpath]
        overrides = meta.get("overrides") or {}
        stages: list[Stage] = []
        instances: dict[str, Instance] = {}
        seen_stages: set[str] = set()
        for entry in _list(meta.get("stages")):
            if isinstance(entry, dict):
                self.keys(fpath, entry, KEYS["flow_stage"], "stages[]")
            use = entry if isinstance(entry, str) else entry.get("use")
            if use in seen_stages:
                self.err(fpath, f"stage `{use}` appears twice")
                continue
            seen_stages.add(use)
            st = self.stage(use, {} if isinstance(entry, str) else entry, overrides, instances, files)
            if st is not None:
                stages.append(st)
        for sid in overrides:
            if sid not in instances:
                self.err(fpath, f"`overrides.{sid}`: no instance `{sid}` in this flow")
        flow = Flow(name, meta.get("description", ""), str(meta.get("version", "")), body, stages, instances,
                    {}, {}, {}, {}, self.problems, files)
        self.graph(flow)
        self.definitions(flow, fpath)
        return flow

    def stage(self, name: str, entry: dict, overrides: dict, instances: dict, files: list) -> Stage | None:
        folder = self.lookup.folder("stages", name)
        if folder is None or not (folder / "STAGE.md").is_file():
            self.err(f"stages/{name}", f"no stage `{name}`")
            return None
        spath = folder / "STAGE.md"
        files.append(spath)
        try:
            meta, body = T.split(spath)
        except T.FlowFileError as exc:
            self.err(spath, exc.reason)
            return None
        self.keys(spath, meta, STAGE_KEYS)
        self.common(spath, meta, name)
        decls = self.params(spath, meta.get("params"))
        params = {k: p.default for k, p in decls.items()}
        params.update(entry.get("params") or {})
        params.update(self.config_params("stages", name))
        for k, v in params.items():
            if k not in decls:
                self.err(spath, f"stage param `{k}` is not declared")
            elif (bad := check_value(decls[k], v)):
                self.err(spath, f"stage param `{k}`: {bad}")
        for k, p in decls.items():
            if p.required and params.get(k) is None:
                self.err(spath, f"stage param `{k}` is required and has no value")
        drop = set(entry.get("drop") or [])
        listed: set[str] = set()
        chain: list[str] = []
        any_tasks = False
        for st in _list(meta.get("steps")):
            if isinstance(st, dict):
                self.keys(spath, st, KEYS["stage_step"], "steps[]")
            use = st if isinstance(st, str) else st.get("use")
            sid = use if isinstance(st, str) else (st.get("as") or use)
            listed.add(sid)
            if sid in drop:
                continue
            when = None if isinstance(st, str) else st.get("when")
            if when is not None:
                bad = T.check_condition(when, set(decls))
                if bad:
                    self.err(spath, f"`when` of `{sid}`: {bad[0]}")
                    continue
                if not T.evaluate(when, params):
                    continue
            if sid in instances:
                self.err(spath, f"instance id `{sid}` is used twice in the flow (give one of them `as`)")
                continue
            with_ = {} if isinstance(st, str) else dict(st.get("with") or {})
            for k, v in list(with_.items()):  # "{{stage param}}": the stage's value, or unset when it has none
                m = T.PLACEHOLDER.fullmatch(str(v)) if isinstance(v, str) else None
                if m:
                    if m.group(1) not in decls:
                        self.err(spath, f"`with` of `{sid}`: `{v}` is not a stage param")
                    if params.get(m.group(1)) is None:
                        del with_[k]
                    else:
                        with_[k] = params[m.group(1)]
            gate = None if isinstance(st, str) else st.get("gate")
            inst = self.step(use, sid, name, with_, gate, overrides.get(sid) or {}, files)
            if inst is None:
                continue
            inst.chain_prev = chain[-1] if chain else None
            chain.append(sid)
            instances[sid] = inst
            any_tasks = any_tasks or bool(inst.tasks)
        for d in drop - listed:
            self.err(spath, f"`drop`: `{d}` is not a step of stage `{name}`")
        secs, problems = T.sections(body, {T.SYSTEM_PROMPT})
        for p in problems:
            self.err(spath, p)
        if any_tasks and T.SYSTEM_PROMPT not in secs:
            self.err(spath, "a step of this stage has tasks: the body needs a `SYSTEM PROMPT` section")
        return Stage(name, folder, params, chain, secs.get(T.SYSTEM_PROMPT))

    # -- one step -----------------------------------------------------------------------------

    def step(self, name: str, sid: str, stage: str, with_: dict, stage_gate, override: dict, files: list) -> Instance | None:
        folder = self.lookup.folder("steps", name)
        where = f"steps/{name}/STEP.md"
        if folder is None or not (folder / "STEP.md").is_file():
            self.err(where, f"no step `{name}` (used by stage `{stage}`)")
            return None
        ppath = folder / "STEP.md"
        try:
            meta, body = T.split(ppath)
        except T.FlowFileError as exc:
            self.err(ppath, exc.reason)
            return None
        self.keys(ppath, meta, STEP_KEYS)
        self.common(ppath, meta, name)
        decls = self.params(ppath, meta.get("params"))
        params = {k: p.default for k, p in decls.items()}
        for source, values in (("STAGE `with`", with_), ("FLOW `overrides.with`", override.get("with") or {}),
                               (f"config `steps.{sid}.params`", self.config_params("steps", sid))):
            for k, v in values.items():
                if k not in decls:
                    self.err(ppath, f"{source}: `{k}` is not a param of `{name}`")
                    continue
                bad = check_value(decls[k], v)
                if bad:
                    self.err(ppath, f"{source}: param `{k}` {bad}")
                params[k] = v
        for k, p in decls.items():
            if p.required and params.get(k) is None:
                self.err(ppath, f"instance `{sid}`: param `{k}` is required and has no value")
        names = set(decls)

        def sub(value, what: str):
            if not isinstance(value, str):
                return value
            try:
                return T.fill(value, params, where=f"{sid}: {what}")
            except KeyError as exc:
                self.err(ppath, str(exc.args[0]))
                return value

        def when_ok(item: dict, what: str) -> bool:
            cond = item.get("when")
            if cond is None:
                return True
            bad = T.check_condition(cond, names)
            if bad:
                self.err(ppath, f"`when` of {what}: {bad[0]}")
                return False
            return T.evaluate(cond, params)

        inputs = []
        for i in _list(meta.get("inputs")):
            self.keys(ppath, i, KEYS["input"], "inputs[]")
            if not i.get("artifact"):
                self.err(ppath, "an input has no `artifact`")
                continue
            inputs.append(Input(sub(i["artifact"], "input"), sub(i.get("path"), "input path"),
                                bool(i.get("required", True)), bool(i.get("hashed", True)),
                                bool(i.get("llm_visible", True))))
        outputs = []
        for o in _list(meta.get("outputs")):
            self.keys(ppath, o, KEYS["output"], "outputs[]")
            if not o.get("artifact"):
                self.err(ppath, "an output has no `artifact`")
                continue
            if not when_ok(o, f"output `{o.get('artifact')}`"):
                continue
            mode = o.get("mode", "create")
            if mode not in ("create", "update", "seed"):
                self.err(ppath, f"output `{o['artifact']}`: mode `{mode}`")
            if mode != "update" and not o.get("path"):
                self.err(ppath, f"output `{o['artifact']}` needs a `path`")
            if o.get("schema") and not (folder / o["schema"]).is_file():
                self.err(ppath, f"output `{o['artifact']}`: schema `{o['schema']}` is not in the step's folder")
            view = o.get("view")
            if isinstance(view, str):
                view = {"kind": view}
            if isinstance(view, dict):
                self.keys(ppath, view, KEYS["view"], "view")
                kind = view.get("kind")
                if kind not in VIEW_KINDS:
                    self.err(ppath, f"output `{o['artifact']}`: view kind `{kind}` is not one of {list(VIEW_KINDS)}")
                if view.get("review") and kind not in ("sections", "table"):
                    self.err(ppath, f"output `{o['artifact']}`: `review` needs a `sections` or `table` view")
                if kind == "table" and not all(view.get(k) for k in ("rows", "id", "columns")):
                    self.err(ppath, f"output `{o['artifact']}`: a table view needs `rows`, `id`, `columns`")
                if view.get("template"):
                    view = {**view, "template": sub(view["template"], "view.template")}
            outputs.append(Output(sub(o["artifact"], "output"), sub(o.get("path"), "output path"), mode,
                                  bool(o.get("user_provided", False)), o.get("schema"),
                                  [sub(x, "excludes") for x in _list(o.get("excludes"))], view))
        units = meta.get("units")
        if units is not None:
            self.keys(ppath, units, KEYS["units"], "units")
            if not isinstance(units, dict) or not units.get("name") or not units.get("from"):
                self.err(ppath, "`units` needs `name` and `from`")
        tools = []
        for t in _list(meta.get("tools")):
            self.keys(ppath, t, KEYS["tool"], "tools[]")
            req = t.get("required", True)
            if not isinstance(req, bool):
                bad = T.check_condition(req, names)
                req = False if bad else T.evaluate(req, params)
                if bad:
                    self.err(ppath, f"`required` of tool `{t.get('role')}`: {bad[0]}")
            tools.append({"role": sub(t.get("role"), "tool role"), "required": req, "doc": t.get("doc", "")})
        packages = []
        for pk in _list(meta.get("packages")):
            self.keys(ppath, pk, KEYS["package"], "packages[]")
            src = pk.get("source") or {}
            if not isinstance(src, dict) or not src.get("git") or not src.get("ref"):
                self.err(ppath, f"package `{pk.get('name')}`: `source` needs `git` and `ref`")
            req = pk.get("required", True)
            if not isinstance(req, bool):
                bad = T.check_condition(req, names)
                req = False if bad else T.evaluate(req, params)
                if bad:
                    self.err(ppath, f"`required` of package `{pk.get('name')}`: {bad[0]}")
            packages.append({**pk, "required": req})
        passes = []
        for c in _list(meta.get("pass")):
            self.keys(ppath, c, KEYS["pass"], "pass[]")
            if not when_ok(c, f"pass check `{c.get('check')}`"):
                continue
            check = str(c.get("check", ""))
            if check.split(" ", 1)[0] not in CHECKS:
                self.err(ppath, f"check `{check}`: the kind is not one of {list(CHECKS)}")
            if c.get("on_fail", "fail") not in ("fail", "warn"):
                self.err(ppath, f"check `{check}`: `on_fail` is `fail` or `warn`")
            passes.append({"check": sub(check, "pass check"), "on_fail": c.get("on_fail", "fail"), "doc": c.get("doc", "")})
        gate = meta.get("gate", "auto")
        for g in (gate, stage_gate, override.get("gate")):
            if g is not None and g not in GATES:
                self.err(ppath, f"gate `{g}` is not one of {list(GATES)}")
        gate = override.get("gate") or stage_gate or gate
        configured = self.config.gate_mode(sid) if self.config is not None else None
        gate = configured or gate
        tasks: list[Task] = []
        declared_tasks = []
        for t in _list(meta.get("tasks")):
            self.keys(ppath, t, KEYS["task"], "tasks[]")
            if not t.get("name"):
                self.err(ppath, "a task has no `name`")
                continue
            declared_tasks.append(t["name"])
            out = t.get("output", "markdown")
            if out not in ("markdown", "text") and not (folder / out).is_file():
                self.err(ppath, f"task `{t['name']}`: output schema `{out}` is not in the step's folder")
            if t.get("per_unit") and units is None:
                self.err(ppath, f"task `{t['name']}` is `per_unit` but the step has no `units`")
            if not when_ok(t, f"task `{t['name']}`"):
                continue
            tasks.append(Task(t["name"], out, sub(t.get("to"), "task to"), bool(t.get("per_unit", False))))
        secs, problems = T.sections(body, set(declared_tasks))
        for p in problems:
            self.err(ppath, p)
        for tn in declared_tasks:
            if tn not in secs:
                self.err(ppath, f"task `{tn}` has no section `<!-- {tn} -->` in the body")
        for t in tasks:
            t.prompt = secs.get(t.name, "")
        llm_tools = _list(meta.get("llm_tools"))
        for tool in llm_tools:
            if tool not in LLM_TOOLS:
                self.err(ppath, f"llm tool `{tool}` is not one of {list(LLM_TOOLS)}")
        write = [sub(w, "write") for w in _list(meta.get("write"))]
        if set(llm_tools) & {"Write", "Edit"} and not write:
            self.err(ppath, "`Write` or `Edit` needs `write`")
        out_names = {o.artifact for o in outputs}
        for w in write:
            if w not in out_names:
                self.err(ppath, f"`write`: `{w}` is not an output of the step")
        for t in tasks:
            if t.to and t.to not in out_names:
                self.err(ppath, f"task `{t.name}`: `to` `{t.to}` is not an output of the step")
        for kind in ("questions", "answers"):
            if "design_choice" in _list(meta.get(kind)):
                self.err(ppath, f"`design_choice` is built in: it is not listed in `{kind}`")
        skills = _list(meta.get("skills"))
        for s in skills:
            sk = self.lookup.folder("skills", s)
            if sk is None or not (sk / "SKILL.md").is_file():
                self.err(ppath, f"skill `{s}` is not found")
            else:
                self.skill(sk)
        assets = [sub(a, "asset") for a in _list(meta.get("assets"))]
        for a in assets:
            if not str(a).startswith(("templates/", "rules/", "knowledge/")):
                self.err(ppath, f"asset `{a}` is not under templates/, rules/ or knowledge/")
        return Instance(
            id=sid, step=name, stage=stage, folder=folder, version=str(meta.get("version", "")),
            description=str(meta.get("description", "")), params=params, param_decls=decls, gate=gate,
            inputs=inputs, outputs=outputs, assets=assets, tools=tools, packages=packages, passes=passes,
            tasks=tasks, questions=_list(meta.get("questions")), answers=_list(meta.get("answers")),
            handback=_list(meta.get("handback")), receives=_list(meta.get("receives")), llm_tools=llm_tools,
            mcp_tools=_list(meta.get("mcp_tools")), write=write, skills=skills, units=units,
            has_code=(folder / "step.py").is_file(), has_addon=(folder / "addon.py").is_file())

    def skill(self, folder: Path) -> None:
        path = folder / "SKILL.md"
        try:
            meta, _ = T.split(path)
        except T.FlowFileError as exc:
            self.err(path, exc.reason)
            return
        self.keys(path, meta, KEYS["skill"])
        if meta.get("name") != folder.name:
            self.err(path, f"`name` is `{meta.get('name')}`, not the folder `{folder.name}`")
        if not meta.get("description"):
            self.err(path, "`description` is required")

    # -- the graph ----------------------------------------------------------------------------

    def graph(self, flow: Flow) -> None:
        for sid in flow.order():
            inst = flow.instances[sid]
            for o in inst.outputs:
                if o.mode in ("create", "seed"):
                    other = flow.producers.get(o.artifact)
                    if other and other != sid:
                        self.err(inst.folder / "STEP.md", f"artifact `{o.artifact}` is also created by `{other}`")
                    flow.producers.setdefault(o.artifact, sid)
                else:
                    flow.updaters.setdefault(o.artifact, []).append(sid)
            for k in inst.answers:
                if k in flow.answers and flow.answers[k] != sid:
                    self.err(inst.folder / "STEP.md", f"question kind `{k}` is also answered by `{flow.answers[k]}`")
                flow.answers.setdefault(k, sid)
            for k in inst.receives:
                if k in flow.receivers and flow.receivers[k] != sid:
                    self.err(inst.folder / "STEP.md", f"problem kind `{k}` is also received by `{flow.receivers[k]}`")
                flow.receivers.setdefault(k, sid)
        for art, ups in flow.updaters.items():
            if art not in flow.producers:
                self.err(flow.instances[ups[0]].folder / "STEP.md", f"`{art}` is updated but no step creates it")
        for sid in flow.order():
            inst = flow.instances[sid]
            where = inst.folder / "STEP.md"
            if inst.chain_prev:
                inst.deps.add(inst.chain_prev)
            for i in inst.inputs:
                if i.path:
                    if i.artifact in flow.producers:
                        self.err(where, f"input `{i.artifact}` has a `path` but `{flow.producers[i.artifact]}` creates it")
                    continue
                producer = flow.producers.get(i.artifact)
                if producer is None:
                    if i.required:
                        self.err(where, f"input `{i.artifact}` is written by no step of the flow and has no `path`")
                    continue
                if producer != sid:
                    inst.deps.add(producer)
                inst.deps |= {u for u in flow.updaters.get(i.artifact, []) if u != sid}
            for o in inst.outputs:  # an update runs after the step that creates the artifact
                if o.mode == "update" and o.artifact in flow.producers and flow.producers[o.artifact] != sid:
                    inst.deps.add(flow.producers[o.artifact])
        for sid in flow.order():  # no step depends on itself
            if sid in flow.upstream(sid):
                self.err(flow.instances[sid].folder / "STEP.md", f"`{sid}` depends on itself (a cycle)")
        for sid in flow.order():
            inst = flow.instances[sid]
            where = inst.folder / "STEP.md"
            up = flow.upstream(sid)
            for k in inst.handback:
                rec = flow.receivers.get(k)
                if rec is None:
                    self.err(where, f"handback `{k}`: no step of the flow receives it")
                elif rec != sid and rec not in up:
                    self.err(where, f"handback `{k}` goes to `{rec}`, which `{sid}` does not depend on")
        order = flow.order()
        for sid in order:  # a step needing the output of a step listed after it in its own stage
            st = flow.stage_of(sid)
            later = set(st.steps[st.steps.index(sid) + 1:])
            bad = flow.instances[sid].deps & later
            if bad:
                self.err(flow.instances[sid].folder / "STEP.md",
                         f"`{sid}` needs `{', '.join(sorted(bad))}`, listed after it in stage `{st.name}`")

    def definitions(self, flow: Flow, flow_file: Path) -> None:
        for inst in flow.instances.values():
            parts = [inst.folder]
            parts += [p for s in inst.skills if (p := self.lookup.folder("skills", s)) is not None]
            stage = flow.stage_of(inst.id)
            parts += [stage.folder / "STAGE.md", flow_file]
            inst.definition_hash = _hash_tree(parts)


def load_flow(name: str, lookup: Lookup, config=None) -> Flow:
    """Load `name` with the lookup and the config in effect; `flow.problems` lists what is wrong."""
    return _Loader(lookup, config).load(name)


def lookup_for(project_root: Path | None, home: Path | None = None) -> Lookup:
    from q3tui.paths import q3tui_home

    return Lookup(project_root / ".q3tui" if project_root else None, home or q3tui_home())


__all__ = ["Lookup", "check_value", "load_flow", "lookup_for"]
