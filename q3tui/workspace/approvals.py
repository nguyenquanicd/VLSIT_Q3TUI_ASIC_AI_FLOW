"""The project commands and code you allowed (spec/config.md "Commands that come with a project",
spec/extensibility.md "Loading and validation"), kept in `$Q3TUI_HOME/approvals.yaml`, per project."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml

Kind = Literal["command", "code"]


def digest(content: str | bytes) -> str:
    data = content.encode() if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


class Approvals:
    def __init__(self, file: Path):
        self.file = file

    def _read(self) -> list[dict]:
        if not self.file.is_file():
            return []
        return list(yaml.safe_load(self.file.read_text()) or [])

    def allowed(self, project: Path, kind: Kind, content: str | bytes) -> bool:
        """True when this exact command or code was allowed in this project (a changed one is asked again)."""
        h, p = digest(content), str(project.resolve())
        return any(e.get("project") == p and e.get("kind") == kind and e.get("hash") == h for e in self._read())

    def allow(self, project: Path, kind: Kind, content: str | bytes) -> None:
        if self.allowed(project, kind, content):
            return
        entries = self._read()
        entries.append({"project": str(project.resolve()), "kind": kind, "hash": digest(content),
                        "at": datetime.now().isoformat(timespec="seconds")})
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(yaml.safe_dump(entries, sort_keys=False))
