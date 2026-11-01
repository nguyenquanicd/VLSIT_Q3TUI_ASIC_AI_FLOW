"""Whether a tool role can run on this machine (spec/tools.md)."""

from __future__ import annotations

import shlex
import shutil

from q3tui.config.schema import Config


def available(config: Config, role: str) -> str | None:
    """Why `role` cannot run (None when it can): not configured, or its program is not found. A role that loads
    modules or a setup script is found only once they are loaded, so its program is not looked for."""
    spec = config.tools.roles.get(role)
    if spec is None:
        return f"the tool role `{role}` is not configured (tools.roles.{role})"
    if spec.modules or config.tools.modules or config.tools.setup_script:
        return None
    try:
        words = shlex.split(spec.cmd)
    except ValueError:
        words = spec.cmd.split()
    program = next((w for w in words if "=" not in w.split("/")[0]), "")
    if program.startswith("{"):
        return None
    if program and shutil.which(program) is None:
        return f"the program `{program}` of the tool role `{role}` is not found"
    return None
