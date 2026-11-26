---
name: tc-quality
description: The quality bar of a test case - a check that can fail on a real DUT bug, distinguishing stimulus, every side effect, no vacuous or tautological checks. Read it to plan, write or review test cases.
---

# A test case that can fail

A test case is worth something only if **some plausible DUT bug makes it fail**. A check that passes whatever the DUT does is worse
than no check: it reports coverage that does not exist. Every rule below is a way a generated test passed while checking nothing.

Ask for every check: **"which bug in the DUT makes this condition false?"** If the answer is "none", or "only a bug in the testbench",
the check is vacuous: change the stimulus, the observation window or the condition until a real bug would trip it.

## Plan from failure modes, not from features
- Start each requirement from the ways an implementation gets it wrong (a failure mode, FM): an off-by-one, a wrong sign or width
  extension, a field decoded too loosely, a stuck or late signal, a lost or duplicated item, a wrong priority, a reset that misses a
  register, two events in the same cycle, an illegal input accepted. The test case exists to catch those.
- Every failure mode of the plan maps to one check that fails on it, tagged in the file with `// FM<k>:` right above that check.

## Rules

**Q1 - Observe the DUT, never only the testbench.** Every check's condition depends on a value the DUT produced after the stimulus
(an output port, a result read back from DUT memory, a spec-defined probe). A check of the testbench's own constants, tables, or of
inputs the testbench drives itself (`i_ld_en`, its parameter list, a predicate computed from its own data) proves nothing about the
DUT. A requirement that only an elaboration, a compile or a separate build can show (illegal parameters rejected with `$error`, a lint
rule) is not a simulation test case: it is `excluded` with that reason, or a flow check, never a TC that prints `PASS`.

**Q2 - Prove the precondition before a "cleared / did not happen" check.** Before checking that reset cleared a flag, an abort stopped
a transfer, or a wrong-path instruction had no effect, check that the flag was set, the transfer was running, the instruction would
have had a visible effect on the right path. Without it the check passes on a DUT that never set the flag.

**Q3 - Look where the wrong behaviour differs from the right one.** A negative or timing check needs an observation window in which
the buggy DUT would show something else: reset a transmitter while its output is away from the idle level, not when it already
sits at the value reset gives; sample a
"no request" window that a stuck request would actually cover; check both bounds of a latency (a lower bound catches a missing
synchronizer or a skipped state, an upper bound a hang).

**Q4 - Distinguishing stimulus.** Choose data that separates the right result from the plausible wrong ones:
- carries that cross element / byte / lane boundaries (a per-byte add equals a word add when no carry crosses);
- sign bits set (sign versus zero extension), the most negative value, all-ones;
- values different from defaults and reset values (a "keeps its old value" check whose old value equals the new default proves nothing);
- non-commutative operand pairs (a swapped source must change the result), shift amounts at and above the width, unsigned values >= 2^31
  (signed comparison bugs);
- distinct data per element / lane / register / address (a copy from the wrong one must differ);
- a marker in every result slot before the run, different from every expected value (a missing write must not look correct).

**Q5 - Check every side effect, wanted and unwanted.** When a requirement says what is written, check all of it: every field of a
register the stimulus could reach (a write that could alias into a group of registers: read back every register of the group), the neighbouring words,
the tail elements, the registers that must not change. When a requirement says something must not happen, check it for every
instruction / transaction where it could (a "scalar result valid" pulse only for the commands that return one: check it is 0 for the
others too).

**Q6 - Partition illegal / unsupported inputs by field.** For a decoder, an illegal encoding is not only a whole unknown opcode: for each
legal opcode, every field value that makes it illegal (funct3 / funct7 values not defined, reserved bits set, a register field that
must be zero) is an equivalence class with at least one case. Legal neighbours of each illegal case are checked too (the decoder must
not reject them).

**Q7 - Keep every checker on.** Call the testbench's shared monitor check at the end of every test case. Every monitor counter the
testbench keeps is either in that check or checked by the test cases that need it: an unchecked counter is a dead checker. A test that
breaks a rule on purpose masks exactly that checker for exactly those cycles, says so in its header, and clears it afterwards.

**Q8 - Expected values come from the spec, computed independently.** Derive them from the spec or a reference model written from the
spec (not from what the DUT happened to return). Do not loosen a check (`>=` instead of `==`, a mask, a skipped field) unless the
spec leaves that part open, and then say so in a comment.

**Q9 - One check per thing, a message that names it.** One check per function the test exercises (its `functions` in the plan); a failure
message names the function, the case, the expected and the seen value, so the triage can tell which function failed without rerunning.
Random tests log their seed with `` `TC_SEED(seed) `` and can be run again with it.

**Q10 - Finish or fail.** Every wait has a timeout and a timeout is a failed check; a missing result, a hang or an unreadable value
(X / Z) is a failure, never a pass. Compare with `===` / `!==` so X does not slip through.

## What code measures (so write for it)
- Every `` `TC_CHECK `` counts the times it ran: a check never reached (in a branch or a loop the stimulus never enters) is reported as checking
  nothing, and a test case that ran no check at all FAILS. Put the check of each failure mode where every run reaches it.
- A failed test case makes the simulator exit non-zero.
- After the tests pass, requirement-matched bugs are injected into a copy of the RTL (`signoff`): a bug no test catches comes back to the
  testbench as a missing check. Plan the mix of test types (directed, combined, constrained_random, fault_injection, stress) for that.

## Review checklist (one line per test case)
1. For each failure mode: which check catches it, and does that check depend on a DUT value? (Q1)
2. Each "nothing happened / cleared" check: is the precondition checked, and is the window one where a bug shows? (Q2, Q3)
3. Could a plausible wrong implementation produce the same values with this stimulus? (Q4)
4. Are all the side effects the requirement names checked, including "must not happen" ones? (Q5)
5. For illegal-input tests: which field classes are missing? (Q6)
6. Is every monitor / checker still on, and checked at the end? (Q7)
7. Is any expected value or tolerance taken from the DUT rather than the spec? (Q8)
