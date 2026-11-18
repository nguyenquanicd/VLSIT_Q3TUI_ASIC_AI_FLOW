"""Add-on of the ECO flow (q3tui/addons.py): its settings (the inputs, the library, the STA constraints, the fix-round bounds)."""
from __future__ import annotations


def register(api) -> None:
    api.setting("eco_inputs", "library", "Library (.db)", "text",
                "The standard-cell library of the ORG netlist: Design Compiler, Formality and PrimeTime read it (a list in q3tui.yaml for several).")
    api.setting("eco_inputs", "top", "Top module", "text", "Empty: schemas/structured_spec.json metadata.top_module.", nullable=True)
    api.setting("eco_inputs", "rtl", "ORG RTL filelist", "text", "Empty (with the two below): the step asks — the asic flow's or your own.", nullable=True)
    api.setting("eco_inputs", "netlist", "ORG netlist (.v)", "text", "The .sdc beside it is the STA's constraints.", nullable=True)
    api.setting("eco_inputs", "requirement", "ECO requirement (.md)", "text", "What the ECO must change.", nullable=True)
    api.setting("eco_inputs", "ref_name", "ref/ folder name", "text",
                "Where the ORG design is kept: ref/<name>/ (ref/<name>_DDMMYYYY_HHMMSS when taken). Empty: the step asks (default: the top module).",
                nullable=True)
    api.setting("eco_verify", "verify", "Run dv + Sanity again", "text",
                "Project mode: yes / no answers eco_verify's question (empty: it asks). Yes: both must pass before the netlist ECO.", nullable=True)
    api.setting("eco_verify", "max_rounds", "dv / Sanity fix rounds", "int", "Rounds back to eco_rtl for their fixes; empty: pipeline.max_fix_iterations.",
                nullable=True)
    api.setting("eco_sta", "sdc", "STA constraints", "text", "Empty: the .sdc beside the ORG netlist, else constraints/sdc/sdc.tcl.", nullable=True)
    api.setting("eco_sta", "max_rounds", "Timing-fix rounds", "int", "Empty: pipeline.max_fix_iterations.", nullable=True)
    api.setting("eco_apply", "max_rounds", "Patch-fix rounds", "int", "Rounds back to eco_patch when the patch does not apply; empty: pipeline.max_fix_iterations.",
                nullable=True)
