---
label: "3"
title: SPEC — the spec updated to the requirement (AI, project mode)
deps: [eco_eq1]
gate: human
options: {}
view: [eco/spec.diff, schemas/eco_spec.json, spec/spec.md]
---
Project mode (the ECO is on this project's own RTL): the spec documents (`spec/*.md`, not the intent) are updated in place to what the requirement asks, with the smallest change; the ORG spec stays in `ref/<name>/spec/` and `eco/spec.diff` is the change against it. The gate is your review of the diff. External mode (a fire-fighting ECO on RTL from elsewhere): skipped.

<!-- SPEC -->
You update the specification of a block that is already designed, verified and synthesized, for an engineering change order (ECO). The
requirement in the task says what changes. Edit the spec documents listed in the task in place (Edit) so that they specify the block as it
must be after the change, and nothing else: change only the requirements, register / field descriptions, behaviour descriptions, waveforms
and examples the requirement affects; keep every other line, the section structure, the requirement IDs (add a new ID only for a new
requirement, after the existing ones; mark a changed requirement in its text, e.g. "(ECO)"), the names and the wording style. Do not
restructure, reformat or "improve" anything, and do not edit `spec/intent.md`. If the requirement contradicts the spec in a way it does not
settle, take the requirement's reading and say so in `concerns`. Answer in the structured output: a summary, one entry per document you
changed (`file`, `what`), and your concerns.
<!-- /SPEC -->
