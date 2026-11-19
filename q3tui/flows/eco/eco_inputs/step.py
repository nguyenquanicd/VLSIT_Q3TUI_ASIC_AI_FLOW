"""ECO step `eco_inputs`: which ORG RTL (a filelist), ORG netlist and requirement the ECO works on. Paths set in the step's options are used as
they are; otherwise the step asks you: the defaults (what the asic flow leaves) or your own paths. The mode follows from the RTL: the project's
own `src/rtl` is `project` mode (the ECO updates the spec and the RTL in place, dv / Sanity may run again), any other filelist `external`
(fire-fighting). The ORG design is kept in `ref/<name>/` (you are asked the name; lib/ref.py), the netlist with its `.sdc` / `.svf` in
`ref/<name>/netlist/`; `schemas/eco_inputs.json` records the choice, the mode, the ref and the files' hashes.
Its tasks (`tasks/`): inputs, mode, ref, record."""
from __future__ import annotations

from pathlib import Path

from q3tui.flows.eco.eco_inputs.tasks import inputs as inputs_task, mode as mode_task, record as record_task, ref as ref_task
from q3tui.flows.eco.eco_inputs.tasks.inputs import parse_paths  # noqa: F401  (tests import it from here)
from q3tui.flows.eco.lib.base import INPUTS_JSON, EcoStep
from q3tui.pipeline.base import StepContext, StepFailed


class Step(EcoStep):
    name = "eco_inputs"
    title = "ECO inputs"
    tasks = (inputs_task.TASK, mode_task.TASK, ref_task.TASK, record_task.TASK)
    hashed_options = ("rtl", "netlist", "requirement", "top", "ref_name")

    def inputs(self, engine) -> list[Path]:
        chosen, _ = inputs_task.chosen_quiet(self, engine)
        files = [engine.project.root / p for p in (chosen or {}).values()]
        if chosen:  # (the .sdc / .svf beside the netlist are copied too)
            net = engine.project.root / chosen["netlist"]
            files += [net.with_suffix(".sdc"), net.with_suffix(".svf")]
        return [self._q_paths(engine)[1], *[f for f in files if f.is_file()]]

    def outputs(self, engine) -> list[Path]:
        # (not eco/ref.json: a reset deletes a step's outputs, and the pointer must outlive it)
        return [x for x in (self.artifact(engine, INPUTS_JSON),) if x.is_file()]

    def reset_files(self, engine) -> list[Path]:
        # (never eco/ref.json nor ref/: a reset must not snapshot again a project the ECO already changed)
        return [x for x in (self.artifact(engine, INPUTS_JSON), *self._q_paths(engine)) if x.is_file()]

    async def run(self, ctx: StepContext) -> None:
        top = self.top(ctx.engine)
        if not top:
            raise StepFailed("no top module: set `top` of eco_inputs (Settings, or q3tui.yaml step_options.eco_inputs.top)")
        got = inputs_task.run(self, ctx, top)
        if got is None:
            return
        paths, how = got
        root = ctx.project.root
        net, fl = (root / paths["netlist"]).resolve(), (root / paths["rtl"]).resolve()
        mode = mode_task.run(self, ctx, fl)
        rec = ref_task.run(self, ctx, top, mode, fl, net)
        if rec is None:
            return
        record_task.run(self, ctx, top, paths, how, rec)
