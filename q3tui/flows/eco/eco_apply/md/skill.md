---
label: "7"
title: Post NETLIST — the patch applied (Design Compiler)
deps: [eco_patch]
gate: none
options:
  max_rounds: null   # rounds back to eco_patch when the patch does not apply; null: pipeline.max_fix_iterations
view: [eco/netlist/*.v, eco/reports/apply_dc.log, eco/reports/apply_check_design.rpt]
---
Design Compiler reads the ORG netlist, sources `eco/patch/eco_patch.tcl` and then eco_sta's timing fixes (`eco/patch/sta_fix_<n>.tcl`) in order, and writes the Post NETLIST. No compile. A patch that does not apply goes back to eco_patch with Design Compiler's error lines.
