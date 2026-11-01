"""`addon.py`: actions, log readers and importers that a step adds to Q3TUI (spec/extensibility.md "`addon.py`")."""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from q3tui.flowdef.model import Flow, Problem
from q3tui.runtime.code import import_file
from q3tui.tools.readers import BUILT_IN


@dataclass
class Action:
    name: str
    doc: str
    params: dict[str, str]
    fn: Callable
    confirm: bool
    step: str


@dataclass
class Importer:
    name: str
    fn: Callable
    accepts: list[str]
    doc: str
    step: str


@dataclass
class Addons:
    actions: dict[str, Action] = field(default_factory=dict)
    readers: dict[str, Callable] = field(default_factory=dict)
    importers: list[Importer] = field(default_factory=list)  # in the order of the flow's steps
    problems: list[Problem] = field(default_factory=list)
    not_approved: list[Path] = field(default_factory=list)


class AddonApi:
    def __init__(self, addons: Addons, step: str, where: str, reserved: set[str]):
        self.addons, self.step, self.where, self.reserved = addons, step, where, reserved

    def _name(self, name: str, what: str) -> bool:
        if name in self.reserved:
            self.addons.problems.append(Problem(self.where, f"{what} `{name}` takes the name of an Ops action"))
            return False
        if name in self.addons.actions:
            other = self.addons.actions[name].step
            self.addons.problems.append(Problem(self.where, f"{what} `{name}` is also registered by `{other}`"))
            return False
        return True

    def action(self, name: str, doc: str, params: dict[str, str] | None = None, confirm: bool = False):
        def register(fn):
            if self._name(name, "action"):
                self.addons.actions[name] = Action(name, doc, dict(params or {}), fn, confirm, self.step)
            return fn

        return register

    def parser(self, name: str, fn: Callable) -> None:
        if name in BUILT_IN:
            self.addons.problems.append(Problem(self.where, f"log reader `{name}` takes the name of a built-in one"))
        elif name in self.addons.readers:
            self.addons.problems.append(Problem(self.where, f"log reader `{name}` is registered twice"))
        else:
            self.addons.readers[name] = fn

    def importer(self, name: str, fn: Callable, accepts: list[str], doc: str = "") -> None:
        if not self._name(name, "importer"):
            return
        self.addons.importers.append(Importer(name, fn, list(accepts), doc, self.step))
        params = {"files": "the files or folders to import"}
        self.addons.actions[name] = Action(name, doc, params, lambda ops, files: fn(ops, _files(files)), False,
                                           self.step)


def _files(value) -> list[Path]:
    if isinstance(value, (list, tuple)):
        return [Path(v) for v in value]
    return [Path(v) for v in str(value).split()]


def load_addons(flow: Flow, reserved: set[str], *, project_q3: Path | None = None,
                approved: Callable[[Path, bytes], bool] | None = None) -> Addons:
    """The addons of every step of the flow, loaded with the flow; a name taken twice is an error of the flow."""
    addons = Addons()
    seen: set[Path] = set()
    for sid in flow.order():
        inst = flow.instances[sid]
        path = inst.folder / "addon.py"
        if not path.is_file() or path in seen:
            continue
        seen.add(path)
        content = path.read_bytes()
        if project_q3 is not None and path.is_relative_to(project_q3) and approved is not None \
                and not approved(path, content):
            addons.not_approved.append(path)
            continue
        where = f"steps/{inst.step}/addon.py"
        try:
            module = import_file(path, f"q3tui_addons.{inst.step}")
            register = getattr(module, "register", None)
            if register is None:
                addons.problems.append(Problem(where, "no function register(api)"))
                continue
            register(AddonApi(addons, sid, where, reserved))
        except Exception as exc:  # noqa: BLE001 -- an addon that does not load is an error of the flow
            addons.problems.append(Problem(where, f"{type(exc).__name__}: {exc}"))
    return addons


def offer(importers: list[Importer], files: list[Path], ops) -> dict[str, str | None]:
    """Offer the files to every importer in the order of the flow's steps; a file one took is not offered to the
    next. Returns each file and the step that took it (None: nobody)."""
    expanded: list[Path] = []
    for f in files:
        expanded += sorted(p for p in f.rglob("*") if p.is_file()) if f.is_dir() else [f]
    left = list(expanded)
    taken: dict[str, str | None] = {str(f): None for f in expanded}
    for imp in importers:
        mine = [f for f in left if any(fnmatch.fnmatch(f.name, pat) for pat in imp.accepts)]
        if not mine:
            continue
        took = imp.fn(ops, mine) or []
        for t in took:
            taken[str(t)] = imp.step
        left = [f for f in left if str(f) not in {str(t) for t in took}]
    return taken
