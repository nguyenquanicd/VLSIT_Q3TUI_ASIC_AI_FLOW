"""Background runs: a run the TUI starts is a `q3tui run` process of its own, so it goes on while you look at another flow (the
TUI restarts on a flow switch) and ends when you stop the TUI. One per flow: `r` in dv, then in fpga, then in sanity runs the three at
the same time (docs/spec/pipeline.md "Runs of several flows"). The TUI follows each the way it
follows any run of another process (run.<flow>.lock, runs/*/events.jsonl: `Q3TUIApp._tick`); the one `Runner` outlives the app
instances of a `q3tui tui` session."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from q3tui.core.compat import group_kwargs, interrupt, kill_group


class Runner:
    def __init__(self) -> None:
        self.children: dict[str, subprocess.Popen] = {}  # flow -> its background process

    def alive(self, flow: str | None = None) -> bool:
        """`flow`'s run is going on (None: any of them)."""
        kids = self.children.values() if flow is None else [c for c in [self.children.get(flow)] if c is not None]
        return any(c.poll() is None for c in kids)

    def pid(self, flow: str) -> int | None:
        return self.children[flow].pid if self.alive(flow) else None

    def returncode(self, flow: str) -> int | None:
        c = self.children.get(flow)
        return c.poll() if c is not None else None

    def command(self, project, flow: str, start=None, stop=None, only=None, regenerate=()) -> list[str]:
        """`q3tui run` for what the TUI would run in-process: the live model / effort and auto switches go along (a setting changed
        for this session only is not in q3tui.yaml)."""
        cfg = project.cfg
        cmd = [sys.executable, "-m", "q3tui.core.cli", "-C", str(project.root), "--flow", flow,
               "--model", cfg.llm.model, "--effort", cfg.llm.effort or "none", "run"]
        for flag, value in (("--from", start), ("--to", stop), ("--only", only)):
            if value:
                cmd += [flag, value]
        for step in sorted(regenerate or ()):
            cmd += ["--regenerate", step]
        if cfg.pipeline.auto_answer:
            cmd.append("--auto-answer")
        elif cfg.pipeline.auto_approve:
            cmd.append("--auto-approve")
        cmd.append("--spec-review" if cfg.spec.self_review else "--no-spec-review")
        return cmd

    def start(self, project, flow: str, **kw) -> int:
        return self._spawn(project, flow, self.command(project, flow, **kw))

    def start_auto(self, project) -> int:
        """`q3tui auto` (core/chain.py), key `auto`: the TUI follows its flow runs like any other run (run.<flow>.lock, runs/*/events.jsonl)."""
        cfg = project.cfg
        cmd = [sys.executable, "-m", "q3tui.core.cli", "-C", str(project.root), "--model", cfg.llm.model, "--effort", cfg.llm.effort or "none", "auto"]
        return self._spawn(project, "auto", cmd)

    def _spawn(self, project, key: str, cmd: list[str]) -> int:
        if self.alive(key):
            raise RuntimeError(f"a {key} run is already going on (pid {self.pid(key)})")
        log = project.ensure_state_dir() / "tui" / f"run.{key}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as out:
            self.children[key] = subprocess.Popen(cmd, cwd=project.root, stdin=subprocess.DEVNULL, stdout=out, stderr=out, **group_kwargs(),
                                                  env={**os.environ, "NO_COLOR": "1", "COLUMNS": "200"})
        return self.children[key].pid

    def stop(self, flow: str | None = None) -> bool:
        """Ctrl-C to `flow`'s run (None: every run): it cancels the step (its tools are killed by the step) and records the run as cancelled."""
        keys = [k for k in (self.children if flow is None else [flow]) if self.alive(k)]
        for k in keys:
            interrupt(self.children[k].pid)
        return bool(keys)

    def shutdown(self, wait: float = 20.0) -> None:
        """The TUI ends: so do its runs. Gently first (the step cleans up what it started), then for sure (each one's whole group)."""
        if not self.alive():
            return
        self.stop()
        end = time.monotonic() + wait
        while self.alive() and time.monotonic() < end:
            time.sleep(0.2)
        for c in self.children.values():
            if c.poll() is None:
                kill_group(c.pid)  # (its own session / group: Vivado and friends go too)
                c.wait()


_RUNNER = Runner()


def get() -> Runner:
    return _RUNNER
