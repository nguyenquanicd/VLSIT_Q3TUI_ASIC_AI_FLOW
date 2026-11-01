# The project's history (`q3tui/core/history.py`)

Q3TUI keeps its own record of a project: a **version** of the project's files

- each time a step finishes (done or failed), when something changed since the last version: `<flow> · <step>: done`;
- each time a flow **passes** (a run that ended with every step of the flow done and up to date, also a flow the fix loop ran within another
  run): `<flow> passed`, marked **`passed/<flow>`** (the mark moves to each new pass; a pass with nothing changed since that flow's last one
  adds no version);
- when the dv `simulate` step starts and files changed outside a step (by hand, an editor): the version the tests run on.

Each version says which flow, step and run made it (`flow:`, `step:`, `run:` lines).

## Where, and what it is not

It lives in `.q3tui/history/`: a git repository of its own whose files are the project folder. It is Q3TUI's, not yours: it is never pushed and
has no remote. Your own git of the project folder (to push it somewhere) works as before, side by side: the history has its own folder and
index, reads none of your git settings or hooks, and never touches your `.git`. It leaves out `build/` and `.q3tui/`, and what the project's
`.gitignore` leaves out. Runs of several flows that finish steps at the same time take turns (a lock). Off: `pipeline.history: false`;
without git installed there is no history (nothing else changes). A history that cannot be written is a warning, never a failed run.

## What reads it

- **The dv triage** ([dv-flow.md](dv-flow.md) "A failing test is judged"): `simulate` keeps, per test, the version it last passed with
  (`passed` in `schemas/dv_test_results.json`, kept while it fails). A failing test that passed with an earlier version gets a prompt section
  "Tests that passed before": the versions since that changed the RTL (who made them: e.g. `fpga · rtl: done` — an FPGA timing fix), the other
  files changed since, and the RTL diff (that version → now, capped). The change request of a module (`[rtl:<module>] …`) carries that module's
  diff since, so the rtl step fixes what the change broke (keeping what it was made for where it can) instead of starting over.

## Commands

| | |
|---|---|
| CLI | `q3tui history [log] [-n N] [PATH]` · `q3tui history diff VERSION [TO] [--path P] [--own]` · `q3tui history show VERSION PATH` · `q3tui history restore VERSION [PATHS…] [--yes]` |
| TUI | `H` or `/history`: the versions (left) and the highlighted one (right): what it changed, `d` everything since it; `r` restores files from it |
| Assistant | `show_history`, `history_diff`, `show_file_version`, `restore_version` |

A version is named by its id (or the start of it), `passed/<flow>`, or `HEAD~n`. **Restore** writes files or folders (none / `.`: the whole
project) back as they were in a version and deletes the files made since under them; it asks first, backs up what changes to `.q3tui/bkp/`,
records the versions before and after, and waits while a run is going on. The steps that read the restored files are out of date afterwards.
