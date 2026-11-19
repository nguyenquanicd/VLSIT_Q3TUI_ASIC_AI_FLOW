"""Task `mode` of eco_inputs: the mode follows from the RTL — the project's own `src/rtl` is `project` mode (the ECO updates the spec and the
RTL in place, dv / Sanity may run again), any other filelist `external` (fire-fighting)."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.lib import ref as refmod
from q3tui.pipeline.base import StepContext

TASK = ("mode", "project (this project's own RTL) or external (RTL from outside the project)")


def run(step, ctx: StepContext, filelist: Path) -> str:
    mode = refmod.mode_of(ctx.project, filelist)
    step.task(ctx, "mode", "project: this project's own RTL" if mode == "project" else "external: RTL from outside the project")
    return mode
