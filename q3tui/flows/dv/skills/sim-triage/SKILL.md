---
name: sim-triage
description: Decide whose fault a failing simulation test is (RTL, testbench, or spec) and what to ask the owner to change.
---

# Triage of a failing simulation test

You may read everything here: the spec, the requirements, the testbench (`src/tb/`), the RTL and the simulation logs. Decide whose problem each failing test is. This is the same judgment as the
rtl flow's `smoke-triage`, for the dv flow's tests: a plain testbench (a result line `TC_RESULT <tc_id> PASS|FAIL`, `TC_DETAIL <tc_id> FAIL: <msg>` for each failed check) or a UVM one (the UVM report
summary, `VLSIT_DUT_TB_RESULT`).

## Method
1. Read the failure (the status, the note, the log around it) and the test: its file in `src/tb/`, and the requirements it checks.
2. Go back to the **spec** and work out by hand what the right answer is. The spec is the reference, not the RTL and not the testbench.
3. Compare: the testbench's expectation, the RTL's behaviour, the spec's statement.
   - Spec and testbench agree, RTL differs → **RTL bug**: a change request for the module that implements it (name the module, the signal or the state, the cycle, and the behaviour the spec states).
   - Spec and RTL agree, testbench differs → **TB bug**: say what the testbench got wrong (a check that is not what the spec says, a wrong expected value, a timing or sampling mistake, a missing reset,
     a width). A message that contradicts itself (it says a signal is X or Z while it prints 0) is a broken check in the testbench, never an RTL problem.
   - Spec, testbench and RTL agree, the **program or data the test loads** (src/sw/: firmware, test programs, images, golden values — the prepare step's) does
     something else → **prepare bug**: say what is wrong in which file (an instruction used against the ISA / the spec, e.g. a SEW the instruction does not
     write the way the program assumes; a wrong address or layout; a wrong golden value) and what it must do. The RTL that follows the spec is not changed to fit a program.
   - The spec is silent or contradicts itself on this point → **spec issue**: a question for the user; change nothing. Give the ways to settle it as `options` (2–4, your recommendation first), each a complete decision the user can pick as is (e.g. "Revise B16 to …", "Allow changing the generated block in place: …"), with its impact, and the `decision` it waits for (the spec's id for it, e.g. DEC-012: the failures that wait for the same one become one question).
   - You cannot tell → say so with the evidence; do not guess a side.
4. Show it on a run (when you have the debug tools `sim_probe` / `wave_*`): reading the code tells you where to look, a run tells you what happens. Dump the instances
   on the failing check's path, then follow the value back from the check: the first place where it departs from the spec is the fault, on whichever side it is (an RTL
   module, or the testbench's stimulus / sampling). Keep the dumps small (the instances of the path, depth 1; `until_ns` just past the failure) and narrow the time window
   to the failing check. The verdict's `evidence` names the dump (D1, …), the signals, the times and the values against the expected ones: without one, nothing is handed over.
5. A failure with no result line, a hang or a timeout: check the testbench's reset, clock and the end of the run first (does it print its result and `$finish`?), then the RTL.

## Judgment
- Do not "fix" the testbench to match the RTL because that is quicker. A test that agrees with a bug is worthless.
- Never hand over a guess. "I read the whole path and found no wrong gate" is the moment to probe, not to name a module: the fix goes to whoever owns the
  first wrong value you saw.
- Be specific: the test id, the file and the line or signal, the cycle, expected against seen. One precise request is better than a list of hunches.
- For a tb_bug the `id` is the test id exactly as given. The change request then reaches that test's own file only (`tests/tc_*.sv`): when the fault is in the
  shared `tb_top.sv` (an always-on monitor or checker, a helper task the test calls), say `module: top` — then tb_top is changed, not the test. For an rtl_bug
  give the module (the RTL file's name without the extension).
- A module a generator made (the prompt's "Generated RTL"): a bug in it is an rtl_bug like any other when it may be changed in place. When the spec forbids editing it, or
  the settings do, it is a spec issue: the proposal names the choices (fix the generator, allow the change in place, or revise the spec to the generated behaviour).
- If the same request was handed over in an earlier round and the test still fails, say that it did not work and look at why (the request may have been wrong, or the cause is on the other side).
