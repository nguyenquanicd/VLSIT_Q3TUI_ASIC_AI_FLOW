---
label: "9"
title: STA of the Post NETLIST (PrimeTime)
deps: [eco_eq2]
gate: none
options:
  sdc: null          # the constraints; null: ref/<name>/netlist/<top>.sdc (beside the ORG netlist), else constraints/sdc/sdc.tcl
  max_paths: 10
  max_rounds: null   # timing-fix rounds; null: pipeline.max_fix_iterations
view: [eco/reports/sta.md, eco/reports/sta_setup.rpt, eco/reports/sta_hold.rpt, eco/reports/sta_constraints.rpt]
---
PrimeTime on the Post NETLIST: setup / hold paths, all violators, the global summary. Only setup fails (hold before placement is reported). A setup violation gets a timing fix (`eco/patch/sta_fix_<n>.tcl`, sizing / buffering netlist edits), applied by eco_apply after the patch; EQ(2) and STA then run again, up to `max_rounds`.
