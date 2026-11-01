# Assistant

Status: **settled**.

The chat in the TUI: you say what you want, the assistant does it with the same actions
you have. How it is shown (the panel, the cards that ask you) belongs to TUI.

## What it knows

Its system prompt has two parts, neither of which names a flow in code:

1. **The fixed part**, written in Q3TUI: who it is, how it uses its tools, and its rules
   (below).
2. **The flow part**, built by Q3TUI from the flow that is loaded: the body of FLOW.md
   when it has one; the stages and steps with their `description`; and for each step its
   inputs, its outputs (artifact → path) and the kinds of question it asks. For example:
   "Step `parse`: extracts the requirements from the spec. Output: `requirements` →
   `schemas/requirements.json`."

- The flow part changes only when the flow changes; the assistant then starts a new
  session, since the old one knew another flow.
- Each message you send starts with a `[TUI context]` line: the step, the tab and the item
  you are looking at. "This" or "it" means what you are looking at.

## Tools

Its tools are the actions of Ops (Engine, "Engine API"), made from the one list that the CLI
and the TUI use too, so the three can do the same things.

| Group    | Tools                                                                                   |
| -------- | --------------------------------------------------------------------------------------- |
| look     | `status` (the display state of each step), `questions`, `cost`                          |
| run      | `run` (with a scope, and the choice of waiting until it ends), `stop`, `rerun`, `reset` |
| review   | `approve`, `request_change`, `answer`, `answer_all` (every open question with its default, of a step or of the flow), `review_item` (confirm an item, or ask for a change to it) |
| settings | `get_settings`, `set_settings`, `set_gate_mode`                                         |
| ask you  | `ask_user`: a question to you with choices, shown by the TUI                            |
| of steps | every action of the addons of the flow's steps (Extensibility)                         |
| files    | `Read`, `Grep`, `Glob` (and what it may write, below)                                   |

It has no tool that changes the structure of a flow (its STEP.md files, skills): that
is the flow's work, not the project's.

## What it may read and write

What it may read and write follows the step you are looking at, so that it never carries
into a step what that step may not see (Flow definitions, "What the LLM may read"):

| You are looking at          | It may read                                                  | It may write                                                        |
| --------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------- |
| a step                      | what that step's LLM may read (inputs, assets, outputs, skills) | that step's outputs, and the user files that step reads (`inputs[].path`) |
| no step (the overview)      | the whole project                                            | nothing                                                             |

- `.q3tui/state/` is always refused.
- What it writes into an output counts as your hand edit (Engine, "Hand edits").
- To work on another step, you look at that step.

## Confirmations and rules

It asks you to confirm ([Allow] [Decline]) before it:

- resets a step;
- approves by force (past a blocking question or an item not reviewed);
- sets a gate mode to `auto` or `unattended`;
- changes a setting in the user or project layer (by default its `set_settings` writes the
  session layer, like the title bar's menus);
- resets the cost;
- calls an action registered with `confirm=True`;
- acts on another step than the one you are looking at (runs, approves, resets it, or
  sends it a change request).

When you decline, it stops and says so.

Its rules (in the fixed part of its system prompt):

- It approves only when you ask.
- It acts, instead of explaining how to.
- It never promises to do something later ("once X ends I will do Y"): it cannot act after
  its reply. When it must wait for a run, it runs with waiting.
- After acting, it says briefly what changed and what is now stale.
- It cites file names and ids, and replies in the language you write in.

## Session

- One session per project, kept across restarts; its id is kept in
  `.q3tui/state/assistant/` (Workspace & state).
- "New chat" starts a new session, and so does a change of flow.
- Model and effort: `llm.model` and `llm.effort` (Configurations).
- Its tools are always the same, so that the prompt cache is kept. What changes with the
  step you look at is what it may read and write, told in a note at the start of each
  message, with the `[TUI context]` line.
- Compaction is left to the Agent SDK, as for the sessions of steps.
- Its cost is recorded under `assistant`. It does not count towards `pipeline.max_cost`,
  which limits a run of the flow.
