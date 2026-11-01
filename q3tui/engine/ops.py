"""Ops: the only door for the CLI, TUI and assistant (spec/engine.md "Engine API"). It holds only generic
actions; an action of one step is registered by that step's `addon.py`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml

from q3tui.config import ConfigLayers, set_value, unset_value
from q3tui.engine.engine import Engine, EngineError, Scope, StageOutcome, StepStatus
from q3tui.engine.events import Event
from q3tui.engine.state import Request
from q3tui.workspace.approvals import Approvals, Kind
from q3tui.workspace.sites import Site, Sites

# The names an addon's action may not take.
OPS_ACTIONS = (
    "run", "stop", "approve", "request_change", "answer", "reset", "gate_mode", "settings", "cost", "review",
    "install_package", "update_package", "fetch_site", "allow", "deny", "apply_preset",
)
GATES = ("manual", "auto", "unattended")
LAYERS = ("session", "project", "user")


class Ops:
    def __init__(self, engine: Engine, *, home: Path):
        self.engine = engine
        self.home = home
        self.approvals = engine.approvals or Approvals(home / "approvals.yaml")
        engine.approvals = self.approvals
        self.addons = None  # q3tui.runtime.addons.Addons, set when the flow's addons are loaded

    @property
    def config(self) -> ConfigLayers:
        return self.engine.config

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        return self.engine.bus.subscribe(fn)

    # -- what the front ends show ---------------------------------------------------------------

    def status(self, step: str) -> StepStatus:
        return self.engine.status(step)

    def statuses(self) -> list[StepStatus]:
        return [self.engine.status(s) for s in self.engine.flow.order()]

    @property
    def is_running(self) -> bool:
        return self.engine.is_running

    # -- running --------------------------------------------------------------------------------

    async def run(self, *, only: str | None = None, from_: str | None = None, to: str | None = None,
                  stage: str | None = None, rerun: list[str] = (), regenerate: list[str] = ()) -> list[StageOutcome]:
        given = [x for x in (only, stage) if x] + ([from_ or to] if (from_ or to) else [])
        if len(given) > 1:
            raise EngineError("give one scope: `only`, `from`/`to` or `stage`")
        return await self.engine.run(Scope(only, from_, to, stage), rerun=list(rerun), regenerate=list(regenerate))

    def start(self, **scope):
        """Start a run in the background (the TUI)."""
        import asyncio

        return asyncio.ensure_future(self.run(**scope))

    def stop(self) -> None:
        self.engine.stop()

    # -- gates, questions, reviews --------------------------------------------------------------

    def approve(self, step: str, *, force: bool = False) -> None:
        self.engine.approve(step, force=force)

    def request_change(self, step: str, text: str, unit: str | None = None) -> Request:
        return self.engine.request_change(step, text, unit)

    def answer(self, question: str, answer: str, *, hint: str | None = None, kind: str | None = None):
        return self.engine.answer(question, answer, hint=hint, kind=kind)

    def review(self, step: str, artifact: str, item: str, *, confirm: bool = True, text: str = "") -> None:
        self.engine.review(step, artifact, item, confirm=confirm, text=text)

    def reset(self, step: str, *, only: bool = False) -> list[str]:
        return self.engine.reset(step, only=only)

    def gate_mode(self, mode: str | None, step: str | None = None, *, layer: str = "session") -> None:
        """Set (or, with None, remove) `pipeline.gate_mode`, or `steps.<step>.gate` with a step."""
        if mode is not None and mode not in GATES:
            raise EngineError(f"the gate mode is one of {', '.join(GATES)}")
        key = f"steps.{step}.gate" if step else "pipeline.gate_mode"
        self.settings(key, mode, layer=layer)

    def definition_answer(self, steps: list[str], choice: str):
        """`rerun`: those steps run again as an update; `later`: they keep the mark and are not asked again."""
        if choice == "later":
            self.engine.definition_later(steps)
            return None
        if choice == "rerun":
            return self.run(rerun=steps)
        raise EngineError("the choice is `rerun` or `later`")

    # -- settings -------------------------------------------------------------------------------

    def settings(self, key: str, value, *, layer: str = "session") -> None:
        """Set a key in one layer (None removes it): the session is never written; user and project are files."""
        if layer not in LAYERS:
            raise EngineError(f"the layer is one of {', '.join(LAYERS)}")
        cfg = self.config
        if layer == "session":
            if value is None:
                cfg.session_unset(key)
            else:
                cfg.session_set(key, value)
            return
        path = cfg.user_file if layer == "user" else cfg.project_file
        if path is None:
            raise EngineError(f"there is no {layer} config file")
        if value is None:
            unset_value(path, key)
        else:
            set_value(path, key, value)
        cfg.reload()

    # -- cost -----------------------------------------------------------------------------------

    def cost(self) -> dict:
        state = self.engine.state
        return {"total_usd": round(state.cost_usd, 4),
                "steps": {s: round(st.cost_usd, 4) for s, st in state.steps.items()},
                "resets": list(state.cost_resets)}

    def reset_cost(self) -> None:
        self.engine.reset_cost()

    # -- actions of the steps' addons -----------------------------------------------------------

    def actions(self) -> list:
        return list(self.addons.actions.values()) if self.addons else []

    def call_action(self, name: str, **params) -> str:
        """Run an action an addon registered; it returns one line for the log."""
        action = self.addons.actions.get(name) if self.addons else None
        if action is None:
            raise EngineError(f"no action `{name}`")
        unknown = set(params) - set(action.params)
        if unknown:
            raise EngineError(f"action `{name}` takes {', '.join(action.params) or 'no params'}, not {', '.join(unknown)}")
        line = str(action.fn(self, **params))
        self.engine.emit("log", step=action.step, message=line)
        return line

    def import_files(self, files: list[Path]) -> dict[str, str | None]:
        """Offer files to the importers of the flow, in the order of its steps: each file and the step that took
        it (None: nobody)."""
        from q3tui.runtime.addons import offer

        return offer(self.addons.importers if self.addons else [], [Path(f) for f in files], self)

    # -- packages, sites, approvals, presets ---------------------------------------------------

    def _package_source(self, name: str) -> dict:
        for inst in self.engine.flow.instances.values():
            for pk in inst.packages:
                if pk["name"] == name:
                    return pk.get("source") or {}
        raise EngineError(f"no step of the flow uses the package `{name}`")

    def install_package(self, name: str) -> Site:
        src = self._package_source(name)
        return Sites(self.home).install(name, src["git"], str(src["ref"]), as_package=True)

    def update_package(self, name: str) -> Site:
        src = self._package_source(name)
        return Sites(self.home).update(name, str(src["ref"]))

    def fetch_site(self, name: str) -> Site:
        sites = Sites(self.engine.project.q3)
        site = sites.read().get(name)
        if site is None:
            raise EngineError(f"the project has no site `{name}`")
        recorded = sites.read()
        recorded.pop(name)
        sites.write(recorded)
        return sites.install(name, site.git, site.ref)

    def allow(self, kind: Kind, content: str | bytes) -> None:
        self.approvals.allow(self.engine.project.root, kind, content)
        if kind == "command" and content == self.config.config.tools.setup_script:
            self.engine.tool_env.load()  # the tools' environment can be made now

    def deny(self, kind: Kind, content: str | bytes) -> None:
        """Nothing is stored: a command or code not allowed is asked about again next time."""

    def allowed(self, kind: Kind, content: str | bytes) -> bool:
        return self.approvals.allowed(self.engine.project.root, kind, content)

    def apply_preset(self, name: str) -> list[str]:
        """Merge `templates/tools/<name>.yaml` into the user layer; a key already set is never overwritten.
        Returns the keys written."""
        f = self.engine.lookup.file(f"templates/tools/{name}.yaml")
        if f is None:
            raise EngineError(f"no preset `{name}` (templates/tools/{name}.yaml)")
        preset = (yaml.safe_load(f.read_text()) or {}).get("tools") or {}
        cfg = self.config
        if cfg.user_file is None:
            raise EngineError("there is no user config file")
        current = cfg.layers["user"].data.get("tools") or {}
        written: list[str] = []

        def walk(node: dict, have: dict, prefix: str) -> None:
            for k, v in node.items():
                key = f"{prefix}.{k}"
                if isinstance(v, dict) and isinstance(have.get(k), dict):
                    walk(v, have[k], key)
                elif k not in have:
                    set_value(cfg.user_file, key, v)
                    written.append(key)

        walk(preset, current, "tools")
        cfg.reload()
        return written


__all__ = ["OPS_ACTIONS", "Ops"]
