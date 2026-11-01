"""A project: a folder with `.q3tui/`, and the paths Q3TUI owns in it (spec/workspace.md)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

IGNORED = (".q3tui/state/", ".q3tui/sites/", ".q3tui/packages/")


@dataclass(frozen=True)
class Project:
    root: Path

    # -- finding and creating ---------------------------------------------------------------

    @classmethod
    def find(cls, start: Path) -> Project | None:
        """The nearest folder from `start` up that has `.q3tui/` (as git finds `.git/`)."""
        here = start.resolve()
        for folder in (here, *here.parents):
            if (folder / ".q3tui").is_dir():
                return cls(folder)
        return None

    @classmethod
    def open(cls, start: Path) -> Project:
        """The project of `start`; when there is none, `.q3tui/` is created in `start`, which becomes the project."""
        found = cls.find(start)
        if found is not None:
            return found
        project = cls(start.resolve())
        project.create()
        return project

    def create(self) -> None:
        self.q3.mkdir(parents=True, exist_ok=True)
        gitignore = self.root / ".gitignore"
        lines = gitignore.read_text().splitlines() if gitignore.is_file() else []
        missing = [x for x in IGNORED if x not in lines]
        if missing:
            text = "\n".join([*lines, *missing]) + "\n"
            gitignore.write_text(text.lstrip("\n"))

    @property
    def has_run(self) -> bool:
        """A project that has run before opens in the Workspace; one that never ran opens on Home. It has run when the
        engine's state file exists: events (a toast, a download) also write into `state/`, but not this file."""
        return self.pipeline_file.is_file()

    # -- paths --------------------------------------------------------------------------------

    @property
    def q3(self) -> Path:
        return self.root / ".q3tui"

    @property
    def config_file(self) -> Path:
        return self.q3 / "config.yaml"

    @property
    def sites_file(self) -> Path:
        return self.q3 / "sites.yaml"

    @property
    def decisions_file(self) -> Path:
        return self.q3 / "decisions.yaml"

    @property
    def state(self) -> Path:
        return self.q3 / "state"

    @property
    def pipeline_file(self) -> Path:
        return self.state / "pipeline.json"

    @property
    def events_file(self) -> Path:
        return self.state / "events.jsonl"

    @property
    def lock_file(self) -> Path:
        return self.state / "lock"

    @property
    def backups(self) -> Path:
        return self.state / "backups"

    @property
    def assistant_dir(self) -> Path:
        return self.state / "assistant"

    @property
    def tui_dir(self) -> Path:
        return self.state / "tui"

    def session_dir(self, step: str) -> Path:
        return self.state / "sessions" / step

    def loop_dir(self, step: str) -> Path:
        return self.state / "loop" / step

    def work_dir(self, step: str) -> Path:
        return self.state / "work" / step

    def cache_dir(self, step: str) -> Path:
        return self.state / "cache" / step

    def rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root))
        except ValueError:
            return str(path)
