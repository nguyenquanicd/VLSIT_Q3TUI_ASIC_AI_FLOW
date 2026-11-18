---
label: "8"
title: EQ(2) — RTL(F) vs Post NETLIST (Formality)
deps: [eco_apply]
gate: none
options:
  message_filter: []
  extra_tcl: []
  max_rounds: null   # fix rounds before the step fails; null: pipeline.max_fix_iterations
view: [eco/reports/eq2.md, eco/reports/eq2_lec.rpt]
---
Proves the Post NETLIST equal to RTL(F). Not equivalent: `eco/reports/eq2.md` says why, who owns the fix and the recommended fix, and a blocking question asks you how to fix it: the recommended fix, the other step, your own words (to the step the analysis names; `patch:` / `rtl:` first to choose), or stop. The answer goes to that step and the fix loop runs it, the Post NETLIST and EQ(2) again. Under auto-answer (`pipeline.auto_answer`, gate mode `auto_answer` of eco_eq2, --yes) nobody is asked: the recommended fix is sent.

<!-- ADVICE -->
You are an equivalence-checking engineer on an ECO. A block's RTL was changed (RTL(F), the diff in the task), the same change was made in its
gate-level netlist with netlist edits (the patch), and Formality says the edited netlist is not equivalent to RTL(F) (or is inconclusive).
Read the Formality report and log, the RTL diff and the patch (Read / Grep; Grep the netlists for the failing points). Say which compare points
fail, what they have in common, and whose the fix is: `patch` when the edits do not implement the RTL change (a missing / wrong connection, a
wrong cell, an edit on the wrong bit), `rtl` when RTL(F) itself is wrong or the change cannot be made as written, `netlist` or `setup` otherwise.
Write `fix` as the recommended fix: the concrete request for that owner (which cells, nets, pins or RTL lines, and what to change). Answer in the structured output only.
<!-- /ADVICE -->
