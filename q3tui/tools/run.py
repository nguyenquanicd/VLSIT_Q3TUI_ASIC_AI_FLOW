"""Running a tool by role (spec/tools.md "Running a role")."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from q3tui.config import ConfigLayers
from q3tui.tools.readers import Diagnostic, Reader, read_log
from q3tui.tools.roles import ToolEnv

PLACEHOLDER = re.compile(r"\{(\w+)\}")
PROGRESS_S = 60  # a `log` line of the step every so often while a role runs


class ToolError(Exception):
    """The tool cannot be run as asked (a placeholder nobody gave, a command not approved): the step fails."""


class ToolBroken(ToolError):
    """The tool failed without saying why in terms of the design (its command, environment): the step
    fails at once, without spending a fix round."""


@dataclass
class ToolResult:
    role: str
    ok: bool
    returncode: int | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    log: Path | None = None
    timed_out: bool = False
    na: bool = False  # the tool is missing and the step declares it not required
    command: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def errors(self) -> int:
        return sum(d.severity == "error" for d in self.diagnostics)

    @property
    def warnings(self) -> int:
        return sum(d.severity == "warning" for d in self.diagnostics)


def render(cmd: str, values: dict) -> list[str]:
    """The command as arguments, placeholders filled; a list fills several arguments."""
    argv: list[str] = []
    for part in shlex.split(cmd):
        names = PLACEHOLDER.findall(part)
        missing = [n for n in names if n not in values]
        if missing:
            raise ToolError(f"the command needs {{{missing[0]}}} (available: {', '.join(sorted(values))}): {cmd}")
        if len(names) == 1 and part == f"{{{names[0]}}}" and isinstance(values[names[0]], (list, tuple)):
            argv.extend(str(v) for v in values[names[0]])
            continue

        def one(m):
            v = values[m.group(1)]
            return " ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)

        argv.append(PLACEHOLDER.sub(one, part))
    return argv


class ToolRunner:
    def __init__(self, config: ConfigLayers, env: ToolEnv, project_root: Path, work_dir: Callable[[str], Path], *,
                 readers: dict[str, Reader] | None = None, approved: Callable[[str], bool] | None = None):
        self.config, self.env, self.root, self.work_dir = config, env, project_root, work_dir
        self.readers = readers or {}
        self.approved = approved

    async def run(self, step: str, role: str, *, required: bool = True, log: str | None = None,
                  timeout: str = "broken", vars: dict | None = None,
                  progress: Callable[[str], None] | None = None) -> ToolResult:
        cfg = self.config.config
        self.env.ensure(cfg)
        why = self.env.available(role)
        if why:
            if not required:
                return ToolResult(role, False, na=True)
            raise ToolError(why)
        spec = cfg.tools.roles[role]
        if self.config.source(f"tools.roles.{role}.cmd") == "project" and self.approved is not None \
                and not self.approved(spec.cmd):
            raise ToolError(f"command not approved: `{spec.cmd}` (tools.roles.{role}.cmd of the project)")
        workdir = self.work_dir(step)
        workdir.mkdir(parents=True, exist_ok=True)
        values = {k: (str(v) if isinstance(v, Path) else v) for k, v in (vars or {}).items()}
        values |= {"project": str(self.root), "workdir": str(workdir)}
        argv = render(spec.cmd, values)
        cwd = Path(PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), spec.cwd)) if spec.cwd else workdir
        log_path = workdir / (log or f"{role}.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        seconds_allowed = spec.timeout_s or cfg.tools.timeout_s
        started = time.monotonic()
        timed_out = False
        with open(log_path, "wb") as out:  # noqa: ASYNC230 -- the tool writes into it, not this coroutine
            out.write(f"$ {shlex.join(argv)}\n".encode())
            out.flush()
            try:
                proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=self.env.env(role), stdout=out,
                                                            stderr=asyncio.subprocess.STDOUT, start_new_session=True)
            except FileNotFoundError as exc:
                out.write(f"command not found: {exc.filename}\n".encode())
                rc = 127
            else:
                ticker = asyncio.ensure_future(_progress(role, log_path, started, progress)) if progress else None
                try:
                    rc = await asyncio.wait_for(proc.wait(), seconds_allowed)
                except TimeoutError:
                    _kill(proc)
                    await proc.wait()
                    rc, timed_out = None, True
                    out.write(f"\n[q3tui: killed after {seconds_allowed} s (timeout)]\n".encode())
                except asyncio.CancelledError:  # the run was stopped: the tool is killed
                    _kill(proc)
                    await proc.wait()
                    raise
                finally:
                    if ticker is not None:
                        ticker.cancel()
        text = log_path.read_text(errors="replace").split("\n", 1)[-1]
        diags = read_log(spec.parse, text, self.readers)
        result = ToolResult(role, False, rc, diags, log_path, timed_out, command=argv,
                            seconds=round(time.monotonic() - started, 2))
        result.ok = rc in spec.ok_returncodes and not timed_out and result.errors == 0
        if (timed_out and timeout == "broken") or (not timed_out and rc not in spec.ok_returncodes and result.errors == 0):
            tail = "\n".join([x for x in text.splitlines() if x.strip()][-8:])
            what = "timed out" if timed_out else f"exited with {rc} and no error its log reader understands"
            raise ToolBroken(f"the tool `{role}` {what}: a problem of its command or environment, not of the design.\n"
                             f"Command: {shlex.join(argv)[:300]}\nLog: {log_path}\n{tail}")
        return result


async def _progress(role: str, log: Path, started: float, report: Callable[[str], None]) -> None:
    """Every PROGRESS_S: "<role>: running <time> — <the last line of its log>"."""
    while True:
        await asyncio.sleep(PROGRESS_S)
        secs = int(time.monotonic() - started)
        elapsed = f"{secs // 60} min" if secs >= 60 else f"{secs} s"
        try:
            lines = [x for x in log.read_text(errors="replace").splitlines()[-20:] if x.strip()]
        except OSError:
            lines = []
        last = lines[-1].strip()[:160] if lines else ""
        report(f"{role}: running {elapsed}" + (f" — {last}" if last else ""))


def _kill(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
