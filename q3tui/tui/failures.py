"""Failed steps for the TUI (docs/spec/tui.md "When a step fails"): every new failure is said (a notice, the header), whichever flow's run it
was in, and a tool failure (`failure.kind == "tool"` on the step's record: the tool crashed, timed out, is missing or was called wrongly — not
the design's problem, so no fix loop takes it) goes to the assistant. It judges it: fixes what its tools can fix (a step setting, the tool's
role in config/tools.json) and reruns the step once, or tells you what to do. The same failure after its fix: it explains and asks, it does not
fix again; a third time only the notice. What was handled is kept in `.q3tui/tui/failures.json` (code-owned, not the chat)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from q3tui.core.project import Project, read_json, write_json

RECENT_S = 24 * 3600  # a tool failure older than this (the TUI was closed) is only listed, not handed to the assistant
LOG_LINES, LOG_CHARS = 40, 3000
_LOG = re.compile(r"\bLog: (\S+)")
_ROLE = re.compile(r"\bthe `([\w.-]+)` tool\b")


@dataclass(frozen=True)
class Failure:
    step: str
    flow: str
    kind: str  # tool | step
    at: str
    error: str

    @property
    def sig(self) -> str:
        """The same failure again: step, kind and the first line of the error (numbers left out: a pid, a time)."""
        first = re.sub(r"\d+", "#", (self.error or "").strip().splitlines()[0] if self.error and self.error.strip() else "")
        return hashlib.sha256(f"{self.step}|{self.kind}|{first[:200]}".encode()).hexdigest()[:16]

    def short(self) -> str:
        line = (self.error or "").strip().splitlines()[0] if (self.error or "").strip() else "failed"
        return line if len(line) <= 160 else line[:157] + "…"


def state_file(project: Project) -> Path:
    return project.state_dir / "pipeline.json"


def failed(project: Project) -> list[Failure]:
    """The steps failed now, with what the engine recorded about the failure (records of before it did have none and are left out)."""
    st = read_json(state_file(project), {}) or {}
    out = []
    for name, rec in (st.get("steps") or {}).items():
        f = rec.get("failure") if isinstance(rec, dict) else None
        if rec.get("status") == "failed" and isinstance(f, dict) and f.get("at"):
            out.append(Failure(name, str(f.get("flow") or ""), str(f.get("kind") or "step"), str(f["at"]), str(rec.get("error") or "")))
    return sorted(out, key=lambda f: f.at)


def recent(f: Failure, now: datetime | None = None) -> bool:
    try:
        return ((now or datetime.now()) - datetime.fromisoformat(f.at)).total_seconds() <= RECENT_S
    except ValueError:
        return False


# -- what was handled ---------------------------------------------------------------------------------------------------

def store_path(project: Project) -> Path:
    return project.state_dir / "tui" / "failures.json"


def load(project: Project) -> dict:
    data = read_json(store_path(project), {}) or {}
    return data if isinstance(data, dict) else {}


def note(project: Project, f: Failure) -> int:
    """Record that this occurrence was handled; the number of times this failure (its signature) was handed over, this one included, or 0
    when this occurrence was handled already (another TUI, or before a restart)."""
    data = load(project)
    entry = data.get(f.sig) or {}
    if entry.get("at") == f.at:
        return 0
    entry = {"step": f.step, "flow": f.flow, "at": f.at, "count": int(entry.get("count", 0)) + 1, "reran": False}
    data[f.sig] = entry
    write_json(store_path(project), data)
    return entry["count"]


def take_rerun(project: Project, f: Failure) -> bool:
    """The one rerun the assistant may start for this failure: True the first time (and recorded), False after."""
    data = load(project)
    entry = data.get(f.sig)
    if not entry or entry.get("reran") or entry.get("count", 0) > 1:
        return False
    entry["reran"] = True
    write_json(store_path(project), data)
    return True


def forget_fixed(project: Project) -> None:
    """A step that is no longer failed starts again from 0: its next failure is a new one."""
    data = load(project)
    if not data:
        return
    st = read_json(state_file(project), {}) or {}
    steps = st.get("steps") or {}
    keep = {k: v for k, v in data.items() if (steps.get(v.get("step")) or {}).get("status") in ("failed", "running")}
    if keep != data:
        write_json(store_path(project), keep)


# -- what the assistant is told -----------------------------------------------------------------------------------------

def log_tail(error: str) -> tuple[str, str]:
    """(log path, its last lines) for the log the error names (`Log: <path>`); ("", "") without one."""
    m = _LOG.search(error or "")
    if not m:
        return "", ""
    p = Path(m.group(1))
    try:
        lines = [x for x in p.read_text(errors="replace").splitlines() if x.strip()][-LOG_LINES:]
    except OSError:
        return str(p), ""
    text = "\n".join(lines)
    return str(p), text[-LOG_CHARS:]


def machine() -> str:
    """Memory of this machine, when it can be read (Linux): a tool that died often ran out of it."""
    try:
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line)
        gb = lambda k: int(info[k].split()[0]) / 1024 / 1024  # noqa: E731
        return f"memory {gb('MemTotal'):.0f} GB, {gb('MemAvailable'):.0f} GB available now"
    except (OSError, KeyError, ValueError):
        return "unknown"


def prompt(project: Project, f: Failure, count: int) -> str:
    """The message the assistant gets: the first time judge / fix / rerun or tell; the second time (after its fix) only explain and ask."""
    if count == 1:
        head = (f"[Tool failure] Step `{f.step}` of the {f.flow} flow stopped at {f.at}: its tool failed — not the design (no fix round was spent). "
                "Judge it:\n"
                "- If you can fix it yourself with your tools — a step setting (get_settings / set_settings), the tool's role in config/tools.json "
                "(set_tool_role: timeout_s, env, modules), an option the step offers for this (set_step_option, listed below), or nothing needs fixing (it was passing: the machine was busy) — "
                f"do it, say in a few lines what you changed and why, then call rerun_failed_step(step='{f.step}') once.\n"
                "- Otherwise — the fix needs the RTL or the spec (only ever through a change request to its step), a tool install, more "
                "memory, or a change to Q3TUI itself — change nothing: tell the user the cause, the evidence and exactly what they should do.\n"
                "Keep it short.")
    else:
        head = (f"[Tool failure, again] Step `{f.step}` of the {f.flow} flow failed the same way again ({f.at}). Do not change anything and do "
                "not rerun it: tell the user the cause, what was tried (if anything) and what they need to do.")
    return head + "\n\n" + facts(project, f)


def facts(project: Project, f: Failure) -> str:
    """What is known about a tool failure: the error, the log's end, the tool's role, the step's options, the machine (the TUI's assistant and an
    unattended run's tool fix, core/chain.py, get the same)."""
    path, tail = log_tail(f.error)
    m = _ROLE.search(f.error or "")
    role = m.group(1) if m else ""
    try:
        from q3tui.eda import tools as toolmod

        roles = toolmod.load_tools(project.cfg, project.root).roles
        role_cfg = roles[role].model_dump(exclude_defaults=True) if role in roles else None
    except Exception:  # noqa: BLE001 - no tools file / a broken one: the error says it
        role_cfg = None
    options = project.cfg.pipeline.step_options.get(f.step) or {}
    facts = [f"Error:\n{f.error.strip()}"]
    if tail:
        facts.append(f"Last lines of the log ({path}):\n{tail}")
    if role_cfg is not None:
        facts.append(f"Tool role `{role}` (config/tools.json): {json.dumps(role_cfg)}")
    facts.append(f"Step options of `{f.step}`: {json.dumps(options) if options else '(none set)'}")
    facts.append(f"This machine: {machine()}")
    try:
        from q3tui import flows
        from q3tui.pipeline.engine import Engine

        eng = Engine(project, flow=flows.load_flow(f.flow, project.root)) if f.flow else None
        offered = [(s.name, k, h, s.options.get(k)) for s in (eng.steps if eng else []) for k, h in (getattr(s, "tool_fix_options", None) or {}).items()]
    except Exception:  # noqa: BLE001 - a flow that cannot load: no options to offer
        offered = []
    if offered:
        facts.append("Step options offered for a tool failure (set_step_option; current values):\n"
                     + "\n".join(f"- {s}.{k} = {json.dumps(v)}: {h}" for s, k, h, v in offered))
    peaks = memory_peaks(project, role_cfg.get("cmd", "") if role_cfg else "")
    if peaks:
        facts.append("Memory the same tool reported in its runs (newest first; a run that needs more than the machine has crashes):\n" + "\n".join(peaks))
    return "\n\n".join(facts)


_PEAK = re.compile(r"peak\s*mem\w*\s*(?:\((mb|gb|kb)\))?\s*[:=]?\s*([\d.]+)\s*(mb|gb|kb)?", re.I)


def memory_peaks(project: Project, cmd: str, limit: int = 6) -> list[str]:
    """The peak memory the tool of `cmd` said in its logs (`Peak Memory(MB): 48846`, the largest per log), newest log first: the logs Q3TUI kept
    (their first line is `$ <command>`) under .q3tui/ and build/."""
    binary = cmd.split()[0] if cmd.split() else ""
    if not binary or "{" in binary:
        return []
    logs = []
    for base in (project.state_dir, project.build_dir):
        if base.is_dir():
            logs += [p for p in base.rglob("*.log") if p.is_file()]
    out = []
    for p in sorted(logs, key=lambda x: x.stat().st_mtime, reverse=True)[:400]:
        try:
            with p.open(errors="replace") as fh:
                if not fh.readline().startswith(f"$ {binary}"):
                    continue
                best = 0.0
                for line in fh:
                    m = _PEAK.search(line)
                    if m:
                        unit = (m.group(1) or m.group(3) or "mb").lower()
                        best = max(best, float(m.group(2)) * {"kb": 1 / 1024, "mb": 1.0, "gb": 1024.0}[unit])
        except OSError:
            continue
        if best:
            when = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            out.append(f"- {project.rel(p)} ({when}): peak {best / 1024:.1f} GB")
        if len(out) >= limit:
            break
    return out
