"""Where Q3TUI's own files are."""

from __future__ import annotations

import os
from pathlib import Path


def q3tui_home() -> Path:
    """`$Q3TUI_HOME`, default `~/.q3tui`."""
    return Path(os.environ.get("Q3TUI_HOME") or "~/.q3tui").expanduser()


def user_config_file() -> Path:
    return q3tui_home() / "config.yaml"


def project_config_file(project_root: Path) -> Path:
    return project_root / ".q3tui" / "config.yaml"
