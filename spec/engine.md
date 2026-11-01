# Engine

Status: **settled**.

How a flow runs: the order of steps, the state of a step, staleness, gates, questions, the
fix loop, and the API that the CLI, TUI and assistant use. The file format of flows belongs
to Flow definitions (the content of artifacts to the flows); file locations to Workspace &
state; the LLM task contract (including checkpoints) to LLM runtime; the step contract to
Extensibility.

## Terms

| Term      | Meaning                                                                                   |
| --------- | ----------------------------------------------------------------------------------------- |
| flow      | an ordered list of stages. One run uses exactly one flow.                                 |
| stage     | an ordered chain of steps                                                                 |
| step      | one unit of work that reads artifacts and writes artifacts                                 |
| LLM task  | one call to the LLM inside a step                                                         |
| artifact  | a named file or set of files that a step writes and other steps read                       |

## Execution

The engine runs only a flow that passed validation (Flow definitions: every input of a step
is written by a step of the flow or is a user file, and no step depends on itself).

- The steps of a stage run one after another, in the order the STAGE.md lists them.
- A step starts when both hold:
  1. the step just before it in its stage is `done` and waits neither for approval nor
     for an answer (the first step of a stage has none);
  2. every step it depends on, in any stage, directly or through other steps (through
     their inputs or the chains of their stages), is `done` (not `stale`) and waits
     neither for approval nor for an answer. A step does not run on a result that is about
     to change: when `lint` has handed a problem back to `rtl`, `synth`, which reads the
     report of `lint`, waits until `rtl` and `lint` have run again.
- A stage starts when its first step can start. What a stage needs is what its steps
  declare: a stage does not declare needs of its own.
- A step never starts while a step that writes one of its inputs (including inputs
  with `hashed: false`) is `running` or `stale`; it waits for that step. A step that is already running
  is not interrupted: if an input changed meanwhile, the step is `stale` when it finishes
  (by the hash) and runs again later.
- Up to `pipeline.max_parallel_stage` stages run at the same time (Configurations).
- A step that waits (approval or question) or fails stops only the chain of its own stage.
  Stages that do not depend on it keep running.
- The engine runs whatever is missing or stale, like `make`. Going back to an earlier
  step happens only through staleness: a step runs again when it becomes stale (see
  "Fix loop").

### Outcome of a run

A run ends when no stage can make progress. Its outcome is the list of the stages that
took part in it, each with its own outcome; they are never merged into one. (How the CLI
turns them into one exit code belongs to CLI.)

| Stage outcome | When                                                                                       |
| ------------- | ------------------------------------------------------------------------------------------ |
| `complete`    | every step of the stage is `done`                                                          |
| `waiting`     | a step of the stage waits for approval or for an answer                                    |
| `failed`      | a step of the stage failed                                                                 |
| `blocked`     | the stage could not start or go on: a step that writes an input of its next step is `waiting` or `failed`, an input is missing, or the cost limit was reached. The outcome names what blocks it. |
| `cancelled`   | the run was stopped                                                                        |

```text
spec          complete
rtl           waiting    (rtl: waiting for approval)
verification  failed     (tb: …)
sanity        blocked    (waits for rtl)
```

### Scope of a run

`run` takes an optional scope; without one it runs the whole flow. Only one scope is given
at a time, except `from` and `to`, which can be given together.

| Scope            | Steps                                                                                   |
| ---------------- | --------------------------------------------------------------------------------------- |
| `only: X`        | X alone                                                                                 |
| `from: X`        | X, the steps after X in its stage, and every stage that needs their outputs (transitively) |
| `to: Y`          | Y, the steps before Y in its stage, and every stage that Y's stage needs (transitively)    |
| `from: X, to: Y` | the steps in both `from: X` and `to: Y`                                                 |
| `stage: S`       | every step of stage S                                                                   |

1. Every step outside the scope that a step inside it needs must be `done` (not `stale`,
   not waiting). Otherwise the run is refused, naming the steps that are not ready.
2. Inside the scope, only `stale` steps and steps that never ran are run; `done` steps
   are skipped.
3. `rerun: [X, …]` runs those steps again as an update even when they are `done`;
   `regenerate: [X, …]` runs them again from scratch.

## Step state

Two axes, plus flags.

| Axis     | Values                                                          |
| -------- | --------------------------------------------------------------- |
| result   | `pending`, `running`, `done`, `stale`, `failed`, `missing_input` |
| approval | `waiting`, `approved` (with `by: you` or `by: auto`)           |

The approval axis has a value only once the step has a result to approve.

| Flag             | Meaning                                                                 |
| ---------------- | ----------------------------------------------------------------------- |
| `origin`         | `generated` (Q3TUI made the output) or `user` (you provided it)         |
| `edited`         | the step's output was changed by hand after the step wrote it           |
| open questions   | the number of open questions of the step                                |
| pending reviews  | the number of items of the step not yet confirmed                       |

A step with `origin: user` is `done` and `approved` by you without running (your own
artifact needs no approval), and receives no decisions from later steps (an answer stays
with the step that asked).

### `missing_input`

A step is `missing_input` when it cannot run and no step of the flow will fix that, that
is when at least one of these holds (all five are declared in the STEP.md and checked by
the engine, the same way for every step):

1. a required input does not exist and no step of the flow writes it;
2. a required tool is not configured or cannot be found;
3. a required package cannot be found.
4. a `path` param has a value that names no existing file or folder.
5. an asset of the step cannot be found.

The message says what is missing. What only the step's code can see when it runs (for
example a top module it cannot decide) is not `missing_input`: the step asks (`ctx.ask`)
or fails with the reason. A step whose input will be written by another step of
the flow is `pending`, not `missing_input`.

### Display state

One value that the CLI, TUI and assistant all show. They never compose their own. The
first that applies wins:

```text
running > failed > missing_input > question waiting > stale > approval waiting > approved > done > pending
```

| Display state    | Condition                                                     |
| ---------------- | ------------------------------------------------------------- |
| running          | result is `running`                                           |
| failed           | result is `failed`                                            |
| missing_input    | result is `missing_input`                                     |
| question waiting | at least one **blocking** question of the step is open        |
| stale            | result is `stale`                                             |
| approval waiting | approval is `waiting`                                         |
| approved         | result is `done` and approval is `approved` by you            |
| done             | result is `done` and approval is `approved` by auto           |
| pending          | anything else                                                 |

`stale` comes before `approval waiting`: approving a result that is about to be updated is
wasted work. Open non-blocking questions are shown as a number. `origin: user` and
`edited` are shown as marks next to the state, not as states.

## Staleness and updates

A step is **stale** when the hash of what it was built from differs from the recorded one.

| In the hash                                    | Not in the hash                              |
| ---------------------------------------------- | -------------------------------------------- |
| inputs (except those with `hashed: false`), and the step's own `seed` outputs once written | the model, the effort |
| the assets the step reads (`assets`)           | tool versions                                |
| pending change requests (including decisions)  | the step's definition (see "Definition changes") |
| params declared `affects_result`               |                                              |

What a step **reads** is in the hash, and a change makes it stale by itself. What a step
**is** (its definition) is not: a change of it is offered to you (see below).

### Definition changes

The definition of a step is every file of its folder (STEP.md, its code, its schemas),
the skills it names, and the STAGE.md and FLOW.md that use it. The engine records the hash of each
step's definition, and its `version`, when the step runs.

- When Q3TUI opens a project, the engine compares the definitions of the flow with the
  recorded ones and emits `definition_changed` with the steps whose definition differs.
- You then choose (how it is asked belongs to TUI and CLI):
  - **run again**: those steps run again as an update (`rerun`, see "Scope of a run"),
    with `ctx.changes.definition_changed` listing the files that changed. The steps after
    them follow through staleness.
  - **later**: nothing runs; those steps carry the mark "definition changed", and the
    question is not asked again until their definition changes again.
- Nothing runs again by itself.

**Updates, not re-runs.** The engine records a hash per input, not only the combined one.
When a step runs again it gets `ctx.changes`, and updates only what those changes affect.
Finer detail than a file (sections, modules) is the step's own work. A step regenerates
from scratch only the first time, after a reset, or when asked to (`regenerate`).

| `ctx.changes`            | Meaning                                                              |
| ------------------------ | -------------------------------------------------------------------- |
| `first_run`              | first run or regenerate: there is no earlier result                  |
| `inputs`                 | each input that was added, changed or removed                        |
| `params`                 | each `affects_result` param that changed, with its old and new value |
| `requests`               | each new request, with its source: `you` (a change request), `decision` (an answer, see "Questions"), `fix` (a problem from a checking step, with its unit, see "Fix loop") |
| `definition_changed`     | the files of the step's definition that changed (a `rerun` after a definition change) |
| `edited_outputs`         | outputs of the step that were edited by hand                         |

### Hand edits

- A hand edit of an output marks the step `edited`. It does not make the step stale and
  does not reopen its gate. Steps that read that output become stale.
- An update starts from the current file, with your edits. The step rewrites only the
  parts its changes touch; your other edits stay.
- Before a step with `edited` outputs updates, the engine backs those outputs up (an
  update that touches an edited part may overwrite it). A regenerate overwrites
  everything, after a backup too.
- `edited` is cleared when the step finishes.

## Gates

Every step has a gate. A gate is the approval of the step's result; a question is something
the step cannot decide alone (see "Questions"). The two are separate: a step whose result
needs no approval can still ask a question. "Review" means only the review of the items
inside a result (a requirement, a section), see below.

| Mode         | Stops                         | Approval after the step     |
| ------------ | ----------------------------- | --------------------------- |
| `manual`     | always, for you to approve    | `waiting` until approved    |
| `auto`       | only for a blocking question  | `approved` by auto          |
| `unattended` | never                         | `approved` by auto          |

- `unattended` takes the default of every question, blocking ones too.
- `on_approve` runs whenever a step is approved, by you or by auto.
- The mode of a step, highest first:

```text
the config                           steps.<step>.gate or pipeline.gate_mode (Configurations:
                                     the highest layer that sets either; in one layer, steps.<step>.gate)
FLOW.md   overrides: {<step>: {gate}} this flow
STAGE.md  steps: [{use, gate}]        this use of the step in the stage
STEP.md   gate                        the step's default (default: auto)
```

What each mode does with what is still open when the step finishes:

|                        | `manual`                                          | `auto`                                         | `unattended`        |
| ---------------------- | ------------------------------------------------- | ---------------------------------------------- | ------------------- |
| blocking question      | stops; cannot be approved until it is answered    | stops                                          | takes the default   |
| non-blocking question  | takes the default when you approve                | takes the default                              | takes the default   |
| item not reviewed      | cannot be approved until every item is confirmed  | does not stop; the item stays "not reviewed"   | as `auto`           |

- A **review item** is a part of the result that the step asks you to look at (a
  requirement it inferred, a section of the spec). You confirm it, or request a change
  (a change request on the same step). A **question** is something the step could not
  decide; its answer may go to another step.
- `pipeline.auto_confirm_reviews` confirms every review item, in every mode. It does not
  change gates.
- `manual`: approving can be forced past the two refusals above.

When an approved step runs again:

| Why it ran again                                                        | Approval                                                        |
| ----------------------------------------------------------------------- | --------------------------------------------------------------- |
| its result is unchanged                                                 | kept                                                            |
| only your decisions changed (`requests` of source `decision`, nothing else) | kept; the rewritten parts become review items "not reviewed" |
| anything else                                                           | `manual`: `waiting` again; `auto`, `unattended`: approved again |

"Unchanged" is decided by the engine: the hashes of the outputs are the same before and
after the run.

## Questions

- The engine owns the questions: storage, state, answers and history. A step raises a
  question with `ctx.ask(...)` and receives decisions through `ctx.changes`.
- A question has these fields:

| Field               | Meaning                                                                                 |
| ------------------- | --------------------------------------------------------------------------------------- |
| `id`                | set by the engine, `<step>-Q<n>`; never reused                                          |
| `key`               | set by the step, named after the decision (`reset.sync`, `fifo.depth`), not after the step. A key is flow-wide: the same key is the same decision whichever step asks it. Asked again in a later run, it is the same question (it keeps its `id` and its answer). |
| `text`              | the question                                                                            |
| `kind`              | required; a question without one is an error of the step                                |
| `blocking`          | whether it blocks (see "Gates")                                                         |
| `default`           | the assumption the step already wrote into its output                                   |
| `options`           | 0 to 4 choices, each with its impact (area, speed, power, complexity); with none, you take the default or give your own answer; you can always give an answer of your own |
| `status`            | `open`, `answered` (by you), `defaulted` (the default was taken), `dropped`             |
| `answer`, `by`, `at` | the answer, who gave it (`you` or `auto`), and when                                    |

- When a step runs again and does not ask an `open` question again, that question becomes
  `dropped`. It stays in the history.
- **Routing comes only from the flow files.** A step lists the kinds it may ask
  (`questions`) and the kinds whose answers it owns (`answers`); the answer to a question
  goes to the step that `answers` its kind. A kind has at most one such step in a flow.
  `design_choice` is built in: it always stays with the step that asked, and no step
  `answers` it.
- A question can only point back: the target must be a step that the asking step depends
  on, directly or through other steps (through its inputs, those with `hashed: false` included, or the
  order of its stage's chain), whatever stage it is in. The order in which the flow files
  list stages and steps plays no part. When the target is not such a step, or has
  `origin: user`, the answer stays with the step that asked, as a `design_choice`.
- An answer becomes a `[decision]` change request on the owner step, which updates; the
  steps after it follow through staleness.
- The step that asked runs again as an update once the owner step has updated: its
  output came from the input before the answer (the owner's answer, the default included,
  changes that input). An answer that stays with the step that asked makes it run again
  as an update, unless it is the question's default (the step wrote that assumption into
  its output).
- `answered` and `defaulted` questions are settled decisions. A later step gets them in
  `ctx.settled`, but only those of the steps it may see (Flow definitions, "What the
  LLM may read"). A question a
  step raises with the `key` of a settled decision is dropped by the engine and never
  asked.

## Fix loop

One mechanism for every step and stage.

A run in which a step hands problems back is a round of the loop: the step's pass checks
are not run in it (Flow definitions, `pass`); they run in the round where it hands back none.

1. A checking step reports each problem with `ctx.handback(kind, unit, key, text)`. Two
   problems with the same `kind`, `unit` and `key` are the same problem (the `text` is
   written by the LLM and differs between rounds). No problem left is a pass.
2. After the gate of the checking step, the engine sends each problem as a change request
   to the step that `receives` that kind, which is a step the checking step depends on
   (Flow definitions). That step becomes stale, so the segment from it to the checking step runs again.
3. The engine counts the rounds of each loop separately, and stops a loop when:

| Condition                                                    | Result |
| ------------------------------------------------------------ | ------ |
| no problem left                                              | pass   |
| the same problems as the round before (the same set of problems) | stop   |
| `pipeline.max_fix_rounds` rounds done (Configurations)       | stop   |

   `pipeline.max_fix_rounds` is the only setting of the fix loop; it applies to every
   loop. When a loop stops without a pass, each problem left becomes a blocking question,
   made by the engine, with three options:

| Option                                   | What follows                                                                                   |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------- |
| fix again (with your hint)               | the hint is sent to the step that received the problem; the round counter goes back to 0; the loop goes on |
| the cause is in another input (a kind that a step of the flow `answers`, with the right content) | a decision of that kind, routed like any answer (see "Questions") |
| accept this problem                      | the problem (by its `kind`, `unit` and `key`) is no longer counted; the checking step passes when no other problem is left |

   Under `unattended` the default is "accept this problem"; it is recorded, so it can be
   looked at afterwards.

   The round counter of a loop is kept across runs. It goes back to 0 only when the loop
   passes, when you step in (you answer a question of the loop, or send a change request
   to a step of the loop), or when the checking step is reset.

4. **Best round.** The best round is the one with the fewest problems; among equal ones,
   the latest. When a loop stops without a pass, the engine restores the best round: the
   outputs of every step of the loop's segment (from the step that received the problems
   to the checking step) and their recorded state, so that no step is stale and nothing
   runs again. The questions are made from the problems of that round. The outputs it
   replaces are backed up.
5. **When the problems are sent** depends on the gate of the checking step:

| Mode         | The problems are sent                                                                   |
| ------------ | --------------------------------------------------------------------------------------- |
| `manual`     | when you approve the checking step. A change request instead of an approval sends nothing; the checking step runs again. |
| `auto`       | as soon as the checking step finishes; after its blocking questions are answered, if it has any |
| `unattended` | as soon as the checking step finishes                                                   |

Only the engine counts rounds, compares the problems of two rounds and sends problems,
and only to steps of the flow that is running.

## Operations

- **Interrupted step.** When a step starts, the engine backs up its current outputs.
  When the run is stopped (the `stop` action stops the whole run) or its process dies, the engine puts those
  outputs back and returns the step to its state before it started, so that no
  half-written file is taken for a hand edit or read by another step. (After a process
  died, this is done when the engine next starts.) When the step was stopped, its stage
  gets the outcome `cancelled`. Reusing the LLM tasks that the step had finished belongs to LLM runtime.
- **Lock.** One run per project at a time. Another process (a second TUI, the CLI) can
  only watch. This is between processes; inside one run, stages run in parallel
  (`max_parallel_stage`) under one engine that alone writes the state.
- **Reset** of a step X applies to X and every step that depends on X, directly or
  through other steps; with `only`, to X alone. For each of these steps it:
  - deletes the files Q3TUI wrote, hand-edited ones included, after backing them up
    (where: Workspace & state);
  - never deletes a file with `origin: user`, nor an output with `mode: seed`;
  - clears its state: result, approval, questions, change requests, and the round counter
    of its fix loop.

  A reset is refused while a run is going on.
- **Cost.** Recorded per step and in total, in `pipeline.json` (Workspace & state); it can
  be reset, and each reset is kept there as an audit entry.
- **Cost limit.** `pipeline.max_cost` (USD, Configurations) limits what one run may spend.
  When it is not set, the engine does not check the cost. When the cost of the
  run reaches it, no new step starts; the steps that are running finish and are not
  interrupted. Every stage that is not finished gets the outcome `blocked`, with the
  reason "cost limit reached".
- **Import** is not the engine's (Workspace & state).

## Engine API

- **Ops is the only door.** The CLI, TUI and assistant call Ops and nothing else; the
  engine's own functions are internal.
- Ops holds only generic actions: run, stop, approve, request a change, answer (one question,
  or every open one with its default: `answer_all`), reset,
  gate mode, settings, cost, review of an item (through views), install or update a
  package, fetch a site, allow or deny a command or code of the project, and apply a
  preset of tools. An action that belongs
  to one step is registered by that step's `addon.py` (Extensibility).
- **Events** are a fixed list of kinds, each with a declared set of fields. Every front end
  and `events.jsonl` read the same events.

### Events

Every event has `ts`, `kind`, `run_id`, `stage` and `step` (empty when they do not apply).

| Kind                | Fields                                                                         |
| ------------------- | ------------------------------------------------------------------------------ |
| `definition_changed` | `steps` (each with `files`, `old_version`, `new_version`)                     |
| `run_started`       | `scope`, `steps`                                                               |
| `run_finished`      | `outcomes` (the outcome of each stage), `cost_usd`                             |
| `stage_started`     |                                                                                |
| `stage_finished`    | `outcome`, `reason`                                                            |
| `step_started`      | `changes` (a summary of `ctx.changes`), `regenerate`                           |
| `step_finished`     | `result` (`done`, `failed`, `cancelled`), `cost_usd`, `outputs`, `error`       |
| `step_skipped`      | `reason` (`up_to_date`, `user`)                                                |
| `task_started`      | `task`, `model`                                                                |
| `task_text`         | `task`, `text`                                                                 |
| `tool_call`         | `task`, `tool`, `input`                                                        |
| `task_finished`     | `task`, `cost_usd`, `turns`, `error`                                           |
| `task_progress`     | `task`, `thinking_tokens`                                                      |
| `approval_waiting`  | `open_questions`, `files`                                                      |
| `approval_resolved` | `decision` (`approved`, `change_requested`), `by`, `accepted_defaults`, `text` |
| `questions`         | `open`, `ids`                                                                  |
| `question_answered` | `id`, `status`, `by`                                                           |
| `loop_round`        | `round`, `problems`, `sent_to`                                                 |
| `loop_stopped`      | `reason` (`pass`, `same_problems`, `max_rounds`), `best_round`                 |
| `log`               | `message`                                                                      |
| `warning`           | `message`                                                                      |
| `error`             | `message`                                                                      |
| `sdk`               | the raw message of the Agent SDK                                               |

All events of a project, in a run or not, are written to one file,
`.q3tui/state/events.jsonl` (Workspace & state); `run_id` is empty for an event outside a
run (an approval after a run, `definition_changed` when Q3TUI opens the project).
`task_progress` is delivered to the front ends but not written there; `sdk` is written
there only.
