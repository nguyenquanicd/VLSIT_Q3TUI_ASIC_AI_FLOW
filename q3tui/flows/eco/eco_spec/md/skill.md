---
label: "3"
title: SPEC — the spec updated to the requirement (AI, project mode)
deps: [eco_eq1]
gate: human
options: {}
view: [eco/spec.diff, schemas/eco_spec.json, spec/spec.md]
---
Project mode (the ECO is on this project's own RTL): the spec documents (`spec/*.md`, not the intent) are updated in place to what the requirement asks, with the smallest change; the ORG spec stays in `ref/<name>/spec/` and `eco/spec.diff` is the change against it. The gate is your review of the diff. External mode (a fire-fighting ECO on RTL from elsewhere): skipped.
