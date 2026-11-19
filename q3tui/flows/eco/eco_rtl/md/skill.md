---
label: "4"
title: RTL(F) — the ORG RTL updated to the requirement (AI)
deps: [eco_spec]
gate: human
options: {}
view: [eco/rtl.diff, schemas/eco_rtl.json, schemas/eco_rtl_plan.json, eco/rtl/*.sv, eco/rtl/*.v, src/rtl/*.sv]
---
The RTL is edited — the project's own `src/rtl` in project mode (the ORG RTL is kept in `ref/`), a copy of the ORG RTL in `eco/rtl/` in external mode — to do what the requirement asks, with the smallest change that does it (an ECO changes as little as it can); `eco/rtl.diff` is the change against the ORG RTL. Before editing, a read-only plan looks for that smallest change: when the requirement or a change request prescribes how to make it and a smaller change gives the same required function, you are asked which one to make (the smaller one is recommended; auto-answer takes it). The gate is your review of the diff: a change request edits the current RTL(F) again, planned the same way.
