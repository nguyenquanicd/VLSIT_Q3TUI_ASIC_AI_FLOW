# Q3TUI

A terminal workspace that runs hardware design flows (FLOW / STAGE / STEP files, from a separate flow repository)
as a make-like pipeline of code and LLM steps.

## The spec

`spec/<aspect>.md` is the source of truth; the code follows it. Each fact has one owner aspect; the others link to it.

- It describes only the target state: no history, no "was / is gone / replaces", no comparison with an
  implementation, nothing left ambiguous (an undecided point goes under "Open items").
- A change to the code that differs from the spec is discussed with the user first, then written into the spec in
  the same commit.
- The flows themselves (vlsit, …) and the content of their artifacts are not specified here.
- Code docstrings point to the spec as `spec/<aspect>.md "Section"`.

## Stack

- Python ≥ 3.11 with `uv` (`uv sync`, `uv run pytest`, `uv run ruff check q3tui tests`; line length 100).
- LLM: the Claude Agent SDK only, through `q3tui/llm/runtime.py`. TUI: Textual, with a library of components
  ported from shadcn (`q3tui/tui/ui/`).

## Layout

- `q3tui/config/`: `config.yaml` in three layers (user, project, session), the schema and its defaults.
- `q3tui/flowdef/`: loading FLOW / STAGE / STEP / SKILL files (lookup, params, conditions, placeholders).
- `q3tui/engine/`: the step graph, staleness by hash, gates, questions, the fix loop, `events.jsonl`, and `Ops`
  (every user action; the TUI, the CLI and the assistant all call it).
- `q3tui/runtime/`: loading step code (`step.py`) and addons, the built-in runner of steps without code, the
  services a step gets (`ctx`), opening a project.
- `q3tui/llm/`: the LLM runtime (sessions, structured output, budgets, what a task may read and write).
- `q3tui/tools/`: tools by role (environment, placeholders, log readers, results).
- `q3tui/workspace/`: the project (`.q3tui/`), `$Q3TUI_HOME`, sites and packages.
- `q3tui/assistant/`: the chat of the TUI, with a tool for each action of `Ops`.
- `q3tui/tui/`: screens, widgets, the component library (`ui/`), diagrams in Markdown.
- `q3tui/step.py`: the API step code imports. `q3tui/cli.py`: the `q3tui` command.

## Conventions

- Deterministic first: what code can compute, code computes; the LLM gets it as ground truth.
- Changes propagate as updates, not re-runs; a later step never works around an earlier step's problem, it hands it
  back to the step that owns it.
- Nothing flow-specific in the core: no step names, no artifact schemas, no EDA tool names.
- The TUI uses the components of `q3tui/tui/ui/` first, and a component of its own only where none fits. Every panel
  (`ResizablePanel`) gives one cell of padding left and right; nothing inside adds its own inset.
- Tests never call a live LLM: patch `q3tui.llm.runtime.query` with a fake. TUI tests use Textual's `run_test`. A
  test that needs an outside tool skips when it is absent.
