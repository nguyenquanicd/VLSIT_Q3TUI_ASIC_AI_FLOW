---
label: "2"
title: EQ(1) — ORG RTL vs ORG netlist (Formality)
deps: [eco_inputs]
gate: none
options:
  message_filter: []
  extra_tcl: []
view: [eco/reports/eq1.md, eco/reports/eq1_lec.rpt]
---
Proves the ORG netlist equal to the ORG RTL before anything changes. A passed `asic_lec` on the same netlist and RTL counts: the step asks whether to use it or check again; without one it asks whether to run EQ(1) (no: skipped, said in the result, the flow goes on). Not equivalent stops the flow with a report of the causes and what to do (`eco/reports/eq1.md`).
