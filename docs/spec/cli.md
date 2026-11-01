# CLI

Status: **deferred**: the CLI is designed after the TUI.

What is known so far:

- The CLI is for people at a terminal and for scripts. The assistant does not use it: its
  tools are the actions of Ops (Assistant).
- `--config key=value` sets the session layer (Configurations).

## Open items

- Everything else: the commands, their output, how they ask (or never ask, in scripts),
  exit codes. Points raised so far, not decided: no shorthand flags besides `--config`;
  importing files, applying a preset, managing sites and packages, and approving project
  commands without the TUI.
