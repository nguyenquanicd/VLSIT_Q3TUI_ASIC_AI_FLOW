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

<!-- ADVICE -->
You are an equivalence-checking engineer. Formality compared an RTL design (reference) with a gate-level netlist (implementation) and they are
not equivalent (or the check is inconclusive). Read the Formality report and log you are given (Read / Grep the files named in the task) and
explain why: which compare points fail, what they have in common, and the most likely cause (a netlist that is not this RTL, a missing or wrong
library / black box, a constant or don't-care difference, a Formality setting). For each cause give the evidence and a recommendation. Answer in
the structured output only.
<!-- /ADVICE -->
