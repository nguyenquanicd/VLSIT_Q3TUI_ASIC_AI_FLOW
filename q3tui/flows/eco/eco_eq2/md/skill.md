---
label: "8"
title: EQ(2) — RTL(F) vs ECO NETLIST (Formality)
deps: [eco_apply]
gate: none
options:
  message_filter: []
  extra_tcl: []
  max_rounds: null   # fix rounds before the step fails; null: pipeline.max_fix_iterations
view: [eco/reports/eq2.md, eco/reports/eq2_lec.rpt]
---
Proves the ECO NETLIST equal to RTL(F). Not equivalent: `eco/reports/eq2.md` says why, who owns the fix and the recommended fix, and a blocking question asks you how to fix it: the recommended fix, the other step, your own words (to the step the analysis names; `patch:` / `rtl:` first to choose), or stop. The answer goes to that step and the fix loop runs it, the ECO NETLIST and EQ(2) again. Under auto-answer (`pipeline.auto_answer`, gate mode `auto_answer` of eco_eq2, --yes) nobody is asked: the recommended fix is sent.
