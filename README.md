# Q3TUI

**Q3 = Quality · Quick · Quorum.** A terminal workspace that runs a hardware design flow (from an intent to
checked RTL and beyond) as a pipeline of steps, some done by code, some by an LLM through the
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk), with EDA tools run by role.

Product of **VLSI Technology**.

- **Flows are data.** A flow (FLOW.md → STAGE.md → STEP.md, with optional `step.py`) lives in its own repository and
  is linked into `$Q3TUI_HOME`; Q3TUI's core depends on no particular flow or artifact.
- **Make-like engine.** The step graph comes from the artifacts the steps read and write; a step whose inputs
  changed is updated, not run again from scratch; gates (`manual`, `auto`, `unattended`) stop for your approval.
- **Tools by role.** A step asks for `sim` or `lint`, never a binary; the commands are in the config. A missing tool
  is reported, never passed.
- **One set of actions.** The TUI, the CLI and the assistant (the chat in the TUI) call the same actions.

## Install

```sh
./install.sh            # installs the q3tui command with uv and creates $Q3TUI_HOME/config.yaml (~/.q3tui)
```

Then install a flow (a site linked into `$Q3TUI_HOME`), and in a folder of your design:

```sh
q3tui                   # opens the TUI: write the intent on Home, then run (Ctrl+R)
q3tui --config llm.effort=high   # a config key for this session only
```

## Specification

The behaviour of Q3TUI is specified in [`spec/`](spec/), one file per aspect: [engine](spec/engine.md),
[configuration](spec/config.md), [flow definitions](spec/flow.md), [extensibility](spec/extensibility.md),
[workspace & state](spec/workspace.md), [LLM runtime](spec/llm-runtime.md), [tools / EDA](spec/tools.md),
[assistant](spec/assistant.md), [TUI](spec/tui.md) and [CLI](spec/cli.md).

## Development

```sh
uv sync
uv run pytest           # no live LLM: tests use a fake
uv run ruff check q3tui tests
```

See [CLAUDE.md](CLAUDE.md) for the layout and the conventions.
