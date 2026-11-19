---
label: "4"
title: RTL(F) — the ORG RTL updated to the requirement (AI)
deps: [eco_spec]
gate: human
options: {}
view: [eco/rtl.diff, schemas/eco_rtl.json, schemas/eco_rtl_plan.json, eco/rtl/*.sv, eco/rtl/*.v, src/rtl/*.sv]
---
The RTL is changed to do what the requirement asks. The objective, in this order: the smallest change in the **netlist** (the ECO patches the synthesized netlist by hand: fewer new / changed cells and rewired nets first), then the smallest change in the RTL. Tasks: **plan** (AI, read-only) looks in the ORG netlist for the smallest netlist change (fewest new cells, existing nets reused, at the register / output where it acts) and writes the RTL change that mirrors it — no guess of a new synthesis; **decide** asks you when the requirement or a change request prescribes a way and a smaller netlist change gives the same required function (the smaller one is recommended; auto-answer takes it); **hand-off** (project mode, RTL the rtl flow made) queues the planned change for the rtl flow's `rtl` step, scoped to each module (`[rtl:<module>]`), and runs the rtl flow (it edits `src/rtl`, lints, smoke-tests; its gate and questions are its own) — or **edit** (external mode, or RTL that is your own) has the AI edit RTL(F) itself; **check** parses RTL(F) and writes `eco/rtl.diff` against the ORG RTL in `ref/`. The gate is your review of the diff: a change request is planned the same way again.
