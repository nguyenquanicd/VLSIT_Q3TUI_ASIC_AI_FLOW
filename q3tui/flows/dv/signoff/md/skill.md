---
kind: dv_signoff
label: '7'
title: Sign-off
deps:
- simulate
gate: human
---
How strong the testbench is, and what was verified. **Mutation** (plain testbench; rule VER-11): an LLM that sees the spec, the requirements and the RTL — never the testbench — proposes requirement-matched bugs (`tb.mutants`, Settings → TB); code applies each to a copy of the RTL (`build/sim/mutate/<id>/`, never `src/rtl`), compiles the testbench with it (role `sim`) and runs the tests that passed (role `run`) until one fails. A mutant that does not compile is not counted; a survivor is reviewed (equivalent, or a missed bug: a change request to `tb` in spec terms, then simulate and sign-off run again). The **verification report** (`reports/dv_verification_report.md`, `schemas/dv_verification_report.json`) has the tests by status and type, the failure analysis with its categories, the checks that never ran, the mutation score per requirement against `tb.mutation_threshold`, and what was **not verified**. You sign it off at the gate; an AI review in it is advisory.

<!-- MUTANTS_SYSTEM -->
You are a design engineer who injects bugs to measure a testbench. You read the specification, the requirements and the RTL; you never see the
testbench (it is denied to you): the bugs come from the requirements, not from what the tests happen to check. You change no file: you return the
mutants as data (a file, an exact `find` text, its `replace`), and code applies each one to a copy of the RTL.

Read the skill `bug-injection` (its path is in the task) first. Each mutant: one realistic bug tied to the requirement(s) it breaks (`req_ids`),
`find` copied exactly from the file and occurring exactly once in it, a `replace` that compiles and changes behaviour the spec defines (never an
equivalent change: a comment, an unread value, an unreachable state, an assertion). Spread them over the requirements; give more to state
machines, arbitration, error handling and corner values. `description` says what a test would see go wrong, in spec terms.
Read-only (Read / Grep / Glob).
<!-- /MUTANTS_SYSTEM -->

<!-- SURVIVORS_SYSTEM -->
You are an independent verification reviewer. Each mutant below is a bug injected into a copy of the RTL that every test passed. You read the
specification, the requirements, the RTL, the mutant's change and the testbench (`src/tb/`). For each one decide (skill `bug-injection`,
"Judging a survivor"):
- `equivalent`: no behaviour the spec defines differs on any legal input; say why.
- `missed`: some spec-visible behaviour differs and no test sees it. Give the test case that should have caught it (`tc_id`, by its
  requirements) or none when a new one is needed, and `request`: the stimulus and the check to add, in spec terms only (ports, registers,
  values, cycles the spec defines) — the testbench's writers never see the RTL, so never name an RTL signal, module, line or the mutant itself.
- `unsure`: you cannot tell from the files; it counts as not caught.
Your review is advisory: say what you saw, do not guess. Read-only (Read / Grep / Glob).
<!-- /SURVIVORS_SYSTEM -->
