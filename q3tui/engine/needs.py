"""`missing_input`: what a step needs that no step of the flow will provide (spec/engine.md "`missing_input`")."""

from __future__ import annotations

from pathlib import Path

from q3tui.config.schema import Config
from q3tui.engine.artifacts import Artifacts, expand
from q3tui.flowdef.load import Lookup
from q3tui.flowdef.model import Instance
from q3tui.tools.roles import available
from q3tui.workspace.sites import Sites


def find_package(name: str, lookup: Lookup) -> Path | None:
    """`<project>/.q3tui/packages/<name>`, then `$Q3TUI_HOME/packages/<name>`."""
    for root in lookup.roots:
        p = root / "packages" / name
        if p.is_dir():
            return p
    return None


def installed_ref(name: str, lookup: Lookup) -> str | None:
    for root in lookup.roots:
        ref = Sites(root).installed_ref(name)
        if ref is not None:
            return ref
    return None


def missing(inst: Instance, artifacts: Artifacts, lookup: Lookup, config: Config, root: Path) -> list[str]:
    """What the step lacks, one line each (empty when nothing is missing)."""
    out: list[str] = []
    flow = artifacts.flow
    for i in inst.inputs:
        if i.required and (i.path or i.artifact not in flow.producers) and not artifacts.exists(i.artifact, inst):
            where = f" ({i.path})" if i.path else ""
            out.append(f"the input `{i.artifact}`{where} does not exist")
    for t in inst.tools:
        if t["required"]:
            why = available(config, t["role"])
            if why:
                out.append(why)
    for pk in inst.packages:
        if not pk["required"]:
            continue
        folder = find_package(pk["name"], lookup)
        if folder is None:
            out.append(f"the package `{pk['name']}` is not installed")
            continue
        want = (pk.get("source") or {}).get("ref")
        have = installed_ref(pk["name"], lookup)
        if want and have and str(have) != str(want):
            out.append(f"the package `{pk['name']}` is at `{have}`, the step needs `{want}`")
        for f in pk.get("must_contain") or []:
            if not (folder / f).exists():
                out.append(f"the package `{pk['name']}` has no `{f}`")
    for name, p in inst.param_decls.items():
        value = inst.params.get(name)
        if p.type == "path" and value and not expand(str(value), root).exists():
            out.append(f"the param `{name}` names `{value}`, which does not exist")
    for a in inst.assets:
        if lookup.file(a) is None:
            out.append(f"the asset `{a}` is not found")
    return out
