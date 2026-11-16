"""Shared pieces of the ASIC flow steps: the RTL (the VLSIT flow's result, read only), the SDC (shared with the FPGA flow's
files in `constraints/sdc/`), where the netlist, the reports and the results go."""

from __future__ import annotations

from pathlib import Path

from q3tui.flows.fpga.lib.base import FpgaStep

PORT_JSON = "asic_port.json"  # schemas/: what the ASIC port check found
SYNTH_JSON = "asic_synth.json"  # schemas/: the synthesis run, numbers and verdict
LEC_JSON = "asic_lec.json"  # schemas/: the equivalence check result
REPORTS = ("area.rpt", "timing.rpt", "qor.rpt", "power.rpt", "constraints.rpt", "check_design.rpt", "check_timing.rpt")


class AsicStep(FpgaStep):
    """Base of the ASIC flow's steps (the RTL / SDC / artifact helpers are the FPGA flow's: the same files)."""

    def workdir(self, engine) -> Path:
        d = engine.project.state_dir / "asic" / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def asic_dir(self, engine) -> Path:
        return engine.project.asic_dir

    def reports_dir(self, engine) -> Path:
        return self.asic_dir(engine) / "reports"

    def netlist(self, engine) -> Path:
        return self.asic_dir(engine) / "netlist" / f"{self.top(engine)}.v"

    def libraries(self, engine) -> list[str]:
        """The `.db` libraries of the synthesis step (`library`: one path or a list; `~` and `$ENV` expand)."""
        import os

        synth = next((s for s in engine.steps if s.kind == "asic.asic_synth"), None)
        raw = (synth.options if synth else self.options).get("library")
        items = [raw] if isinstance(raw, str) else list(raw or [])
        return [str(Path(os.path.expandvars(str(x))).expanduser()) for x in items if str(x).strip()]

    def macros(self, engine) -> dict:
        """What `asic_macro` made (schemas/asic_macro.json; {} before it ran or without the step)."""
        from q3tui.flows.asic.lib import macro

        return self.read(engine, macro.MACRO_JSON, {}) or {}

    def synth_files(self, engine) -> list[Path]:
        """The RTL as the ASIC tools read it: each memory wrapper that has macros replaced by its ASIC body."""
        from q3tui.flows.asic.lib import macro

        return macro.swapped(self.rtl_files(engine), self.macros(engine), engine.project.root)

    def macro_dbs(self, engine) -> list[str]:
        """The .db files of the memory macros (link libraries of Design Compiler, read_db of Formality)."""
        from q3tui.flows.asic.lib import macro

        return macro.macro_dbs(self.macros(engine), engine.project.root)
