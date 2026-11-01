"""The environment of the tools, made once when Q3TUI loads, and whether a role is available (spec/tools.md
"Running a role": Environment, Available)."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
from collections.abc import Callable

from q3tui.config.schema import Config

NOT_APPROVED = "command not approved"


def _program(cmd: str) -> str:
    try:
        words = shlex.split(cmd)
    except ValueError:
        words = cmd.split()
    for w in words:
        if "=" in w and not w.startswith(("/", ".", "{")):  # VAR=value before the program
            continue
        return w
    return ""


class ToolEnv:
    """The kept environment of every role. `approved(command)` says whether a `setup_script` that comes from
    the project layer may run (None: it does not come from the project)."""

    def __init__(self, config: Config, *, approved: Callable[[str], bool] | None = None,
                 base: dict[str, str] | None = None):
        self.config = config
        self.approved = approved
        self.base = dict(base if base is not None else os.environ)
        self.key = ""
        self.common: dict[str, str] | None = None
        self.roles: dict[str, dict[str, str]] = {}
        self.errors: dict[str, str] = {}  # role ("" for every role) -> why its environment could not be made

    def _tools_key(self) -> str:
        return hashlib.sha256(self.config.tools.model_dump_json().encode()).hexdigest()

    def ensure(self, config: Config | None = None) -> None:
        """Load once; again only when the `tools` section changed."""
        if config is not None:
            self.config = config
        if self.key != self._tools_key():
            self.load()

    def load(self) -> None:
        t = self.config.tools
        self.key = self._tools_key()
        self.common, self.roles, self.errors = None, {}, {}
        if t.setup_script and self.approved is not None and not self.approved(t.setup_script):
            self.errors[""] = NOT_APPROVED
            return
        try:
            self.common = self._capture(self.base, t.setup_script, t.modules)
        except RuntimeError as exc:
            self.errors[""] = str(exc)
            return
        for name, role in t.roles.items():
            if not role.modules:
                self.roles[name] = self.common
                continue
            try:
                self.roles[name] = self._capture(self.common, None, role.modules)
            except RuntimeError as exc:
                self.errors[name] = str(exc)

    def _capture(self, env: dict[str, str], setup: str | None, modules: list[str]) -> dict[str, str]:
        if not setup and not modules:
            return dict(env)
        lines = ["set -e"]
        if modules:
            init = self.config.tools.modules_init or '"$MODULESHOME/init/bash"'
            lines.append(f"type module >/dev/null 2>&1 || source {init}")
        if setup:
            lines.append(f"source {setup}")
        if modules:
            lines.append("module load " + " ".join(shlex.quote(m) for m in modules))
        lines.append("env -0")
        what = " and ".join(x for x in (setup and f"`{setup}`", modules and f"modules {', '.join(modules)}") if x)
        try:
            proc = subprocess.run(["bash", "-c", "\n".join(lines)], env=env, capture_output=True, check=False,
                                  timeout=300)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"loading {what} took more than 300 s") from exc
        if proc.returncode != 0:
            tail = proc.stderr.decode(errors="replace").strip().splitlines()[-3:]
            raise RuntimeError(f"loading {what} failed: {' / '.join(tail) or f'exit {proc.returncode}'}")
        out: dict[str, str] = {}
        for item in proc.stdout.split(b"\0"):
            k, sep, v = item.decode(errors="replace").partition("=")
            if sep and k and not k.startswith("BASH_FUNC_"):
                out[k] = v
        return out

    def env(self, role: str) -> dict[str, str]:
        """The environment a run of `role` starts in (its `env` added)."""
        self.ensure()
        spec = self.config.tools.roles[role]
        return {**(self.roles.get(role) or self.common or self.base), **spec.env}

    def available(self, role: str) -> str | None:
        """Why `role` cannot run (None when it can)."""
        self.ensure()
        spec = self.config.tools.roles.get(role)
        if spec is None:
            return f"the tool role `{role}` is not configured (tools.roles.{role})"
        if "" in self.errors:
            return f"the tool role `{role}`: {self.errors['']}"
        if role in self.errors:
            return f"the tool role `{role}`: {self.errors[role]}"
        program = _program(spec.cmd)
        if not program or program.startswith("{"):
            return None
        env = self.roles.get(role) or self.common or self.base
        if shutil.which(program, path=env.get("PATH", "")) is None:
            loaded = [*self.config.tools.modules, *spec.modules]
            after = f" after loading {', '.join(loaded)}" if loaded else ""
            return f"`{program}` (tool role `{role}`) is not found{after}"
        return None


def available(config: Config, role: str) -> str | None:
    """Whether `role` can run, with a fresh environment (for a one-off check)."""
    return ToolEnv(config).available(role)
