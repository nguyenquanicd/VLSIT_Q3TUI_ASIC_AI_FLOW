---
name: bug-injection
description: How to write mutants that measure a testbench - one realistic, requirement-matched bug per mutant, compiles, changes spec-visible behaviour, never equivalent. Read it to propose mutants or to judge a survivor.
---

# Bugs that measure a testbench

A mutant is worth running only if a correct testbench **must** catch it: the bug breaks a requirement in a way the spec lets a test see. The
score is caught / (compiled − equivalent): a mutant that does not compile, or changes nothing observable, measures nothing.

## Which bugs
Inject the bugs a designer really makes, each tied to a requirement (name it in `req_ids`):
- **rule not applied**: a condition dropped (`if (a && b)` → `if (a)`), a case item that falls to default, an illegal input accepted;
- **stuck signal**: an output, a valid, a ready or an enable tied to 0 / 1 (or to its reset value) for all or some cases;
- **one cycle late / early**: a registered signal used where the combinational one was meant, or the reverse; a counter that ends one early / late;
- **off by one**: `<` ↔ `<=`, a bound or a width one short, an index one off;
- **wrong reset value**: one register of a block reset to another value, or not reset;
- **wrong priority**: two requests in the same cycle served in the other order; a clear that loses to a set;
- **wrong extension / width**: sign ↔ zero extension, a truncation, a byte lane swapped;
- **wrong operator**: `+` ↔ `-`, `&` ↔ `|`, `>>` ↔ `>>>`, a comparison signed ↔ unsigned.

Spread them: every requirement with behaviour a simulation can see gets at least one when the count allows; the important and the complex ones
(state machines, arbitration, error handling, corner values) get more. Not only the easy ones: a testbench that only catches stuck outputs is weak.

## How to write one
- One bug per mutant, one place: `find` is a piece of the file copied **exactly** (whitespace and all) that occurs **once** — include enough of the
  line to make it unique; `replace` is the same piece with the bug.
- It must compile with the rest of the design: keep the widths and the names; do not add ports or signals.
- It must change behaviour the spec defines. Not equivalent: no change to a value nobody reads, to a state that cannot be reached, to a comment, to an
  assertion or a `$display`, to a don't-care the spec leaves open. When unsure, pick another place.
- `description` says the bug in spec terms (what a test would see go wrong), not only the code change.
- Never edit generated blocks the spec forbids editing in a way that only the generator could produce; a bug in them is still a bug.

## Judging a survivor
Every test passed on the mutant. Decide, from the spec and the RTL:
- **equivalent**: no behaviour the spec defines differs on any legal input (say why: unreachable, masked later, a don't-care);
- **missed**: some spec-visible behaviour differs and no test sees it — say which input sequence shows it and what the check must be, in spec terms
  (ports, registers, values, cycles), because the testbench never sees the RTL. Name the test case that should have caught it (by its requirements),
  or none when a new test case is needed;
- **unsure**: you cannot tell; it counts as not caught.
