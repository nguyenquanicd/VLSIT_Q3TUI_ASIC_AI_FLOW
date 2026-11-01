"""The alerts of Home (spec/tui.md "Alerts"): the flow's errors, what the steps lack, the project's sites not
fetched, and the unknown keys of the config. No Textual here."""

from __future__ import annotations

import re
from dataclasses import dataclass

from q3tui.runtime.session import Opened
from q3tui.workspace.sites import Sites

ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class AlertSpec:
    severity: str  # error | warning | info
    title: str
    detail: str
    action: str | None = None  # the button's label
    payload: str | None = None  # what the button acts on: settings:<group>, install:<pkg>, fetch:<site>


def alerts(opened: Opened) -> list[AlertSpec]:
    out: list[AlertSpec] = []
    for p in opened.problems:
        out.append(AlertSpec("error", p.message, f"In {p.file}. Fix the flow file, or pick another flow (F6)."))
    eng = opened.engine
    if eng is not None:
        lacking: dict[tuple[str, str], list[str]] = {}
        for sid in eng.flow.order():
            st = eng.status(sid)
            for line in st.missing:
                if line.startswith("the input "):
                    continue  # a user file: the input box of Home, or a step of the flow, gives it
                lacking.setdefault(_thing(line), []).append(sid)
        for (kind, text), steps in lacking.items():
            needed = f"Needed by: {', '.join(steps)}."
            if kind == "tool":
                role = re.search(r"`([^`]+)`", text)
                name = role.group(1) if role else ""
                role_name = re.search(r"tool role `([^`]+)`", text)
                key = role_name.group(1) if role_name else name
                out.append(AlertSpec("error", text[0].upper() + text[1:], f"{needed} Set its command in tools.roles.{key}.",
                                     "Open settings", "settings:tools"))
            elif kind == "package":
                pkg = re.search(r"`([^`]+)`", text).group(1)
                action = "Update" if " is at " in text else "Install"
                out.append(AlertSpec("error", text[0].upper() + text[1:], needed, action, f"install:{pkg}"))
            else:
                out.append(AlertSpec("error", text[0].upper() + text[1:], needed))
    for site in Sites(opened.project.q3).missing():
        out.append(AlertSpec("warning", f"Site `{site.name}` is not fetched", f"{site.git} at {site.ref}.",
                             "Fetch site", f"fetch:{site.name}"))
    for w in opened.warnings:
        out.append(AlertSpec("warning", str(w.message if hasattr(w, "message") else w),
                             f"In {getattr(w, 'file', '') or 'the config'}.", "Open settings", "settings:"))
    return sorted(out, key=lambda a: ORDER[a.severity])


def _thing(line: str) -> tuple[str, str]:
    if "tool role" in line:
        return "tool", line
    if line.startswith("the package"):
        return "package", line
    return "other", line


def first_user_file(opened: Opened) -> str | None:
    """The flow's first user file that a step requires and that is missing (the input box of Home writes it)."""
    eng = opened.engine
    if eng is None:
        return None
    for sid in eng.flow.order():
        for i in eng.flow.instances[sid].inputs:
            if i.path and not any(c in i.path for c in "*?[") and not (eng.root / i.path).exists():
                return i.path
    return None
