---
label: "3"
title: SPEC — the spec updated to the requirement (AI, project mode)
deps: [eco_eq1]
gate: human
options: {}
view: [eco/spec.diff, schemas/eco_spec.json, spec/spec.md]
---
Project mode (the ECO is on this project's own RTL): the spec is updated to what the requirement asks, with the smallest change; the ORG spec stays in `ref/<name>/spec/` and `eco/spec.diff` is the change against it. Tasks: **request** — the requirement (and the change requests: your review, a Sanity `spec` decision) as a change request; **hand-off** — when the spec flow wrote `spec/spec.md`, the request goes to the spec flow's `spec` step and the spec flow runs (spec → parse → config: it patches only the sections the request affects; its gate and questions are its own) — or **edit** — a spec that is your own: the AI edits the spec documents itself; **diff** — `eco/spec.diff` against `ref/`. The gate is your review of the diff. External mode (a fire-fighting ECO on RTL from elsewhere): skipped.
