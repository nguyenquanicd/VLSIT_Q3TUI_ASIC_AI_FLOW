# LLM runtime

Status: **settled**.

## Sessions

- Each step has one LLM session. All the LLM tasks of the step run in it, one after
  another; tasks that run once per unit (`per_unit`) run one unit after another in it.
- The system prompt of a step's session is the `SYSTEM PROMPT` section of its stage's STAGE.md. Every step of
  a stage shares it, so it states the goal and the rules of the stage, not the role of
  one step; what a step does is in its task prompts (the body of its STEP.md), which are
  sent as messages.
- The session of a step is kept across runs and restarts. When the step runs again (a
  problem handed back, an answer, a change request), it goes on in the same session.
- Each task is one query in the step's session. The step's first task (and the first one
  after a reset) opens the session, with the system prompt; every later task, in this run
  or a later one, resumes it.
- The session's id is kept in `.q3tui/state/sessions/<step>/` (Workspace & state). When the
  Agent SDK cannot find it (another machine, cleaned up), a new session is opened and a
  warning says so.
- The tools of a session are the step's (`llm_tools`, `mcp_tools`, Flow definitions), the
  same for every task, so that the prompt cache is kept.
- **Cost.** A resumed session reports the running totals of the whole session; the cost of
  a task is the difference with the totals recorded after the step's previous task.
- Resetting a step starts a new session for it, and so does regenerating it (a session that
  remembers the old result would not start from scratch).
- **Compaction.** When a session reaches the model's context limit, the Agent SDK compacts
  it by itself, as Claude Code does; there is no setting for it. Q3TUI writes a line in the
  step's log when it happens.
- There is no other way of sharing sessions, and no setting for it. Work that must not
  share a session with the rest of a step (for example a review of what the step wrote)
  is a step of its own.

## What a task may read and write

- It may read what the step declares (Flow definitions, "What the LLM may read"): its
  inputs (except those with `llm_visible: false`), assets, own outputs, skills, the files
  its `path` params name and its packages; it may write the outputs listed in `write`. `.q3tui/state/` is always refused.
- A `PreToolUse` hook checks every call of `Read`, `Grep`, `Glob`, `Write` and `Edit`. A
  path outside these lists is refused, with an answer the LLM can act on ("`src/rtl/fifo.sv`
  is not an input of this step").
- `Glob` is replaced by one that lists only the files the task may read. `Grep` without a
  `path` is refused, with the list of the files and folders the task may read, so that the
  LLM searches one of them.
- The LLM is told what it may read and write in a short note at the start of each task's
  message (not in the system prompt, which the whole stage shares).
- **What changed.** When a step runs again as an update (not its first run, not a
  regenerate), the first task of that run starts its message with a short note of
  `ctx.changes` (Engine), for every step, with code or without:

  ```text
  [Q3TUI] What changed since the last run:
  - request (fix, unit top): bad: x stuck
  - input changed: spec
  - param changed: depth 4 → 8
  - you edited: rtl
  ```

  The session remembers the earlier run, so the note is enough for the LLM to change only
  what these touch.

- Q3TUI's own MCP tools follow the same lists. The `mcp_servers` of the config are outside
  services and are not checked by path.
- `Bash` is never given to the LLM: commands run through tools by role (`ctx.tool`) or
  Q3TUI's MCP tools.

## Results

- `output: <file>.schema.json`: the schema is given to the Agent SDK as the structured
  output, and Q3TUI checks the result against it again.
  - A result that does not match is asked for again in the same session, with the list of
    what is wrong, at most 2 times.
  - When the SDK returns no structured output (long Markdown values often break its JSON),
    the task is asked once more for the result as one JSON block in its reply, which is
    then checked the same way.
- `output: markdown` or `text`: the result is the task's last answer.
- A task that still has no valid result fails: `ctx.task` raises, and the step fails unless
  its code handles it.

## Resume after an interruption

When a step is stopped or its process dies, Engine puts its outputs back as they were
before it started. The LLM side follows:

- When a step starts, the last message of its session is recorded. After an interruption
  the session is taken back to that message, so it never remembers the cancelled work.
- A task that made no `Write` or `Edit` call has its result kept as a checkpoint in
  `.q3tui/state/cache/<step>/`, keyed by everything that went into it: the task, its unit,
  its message, the model, the effort, the schema, and the path, size and modification time
  of every file it may read.
- When the step runs again, a task whose key matches a checkpoint gets the kept result
  without calling the LLM, and the log says so. Tasks that wrote files run again.
- The checkpoints of a step are removed when it finishes, when it fails, and when it is
  regenerated.

## Model and limits

| Key (Configurations)  | What it does                                                                        |
| --------------------- | ----------------------------------------------------------------------------------- |
| `llm.model`, `llm.effort` | the model and effort of every task (a step may set its own, `steps.<step>.model` / `effort`) |
| `llm.fallback_model`  | the model the Agent SDK turns to when the main one fails (overloaded, unavailable)  |
| `llm.thinking_budget` | only for a model without effort (Haiku 4.5): the most thinking tokens; `0` turns thinking off, null leaves the model's default |
| `llm.env`             | environment variables given to the Agent SDK's process                              |
| `llm.timeout_s`       | the longest one task may take                                                       |
| `llm.task_max_cost`   | the most one task may spend                                                         |
| `llm.tool_output_limit` | caps what one tool call returns to the model                                      |
| `llm.task_token_budget` | a task that reads more input tokens than this raises a warning                    |

- A task has no limit on its number of turns: the model decides when it is done.
- A task that goes past `llm.timeout_s` or `llm.task_max_cost` is stopped and fails:
  `ctx.task` raises, and the step fails unless its code handles it.
- Going past `llm.task_token_budget` only raises a warning; the task goes on.

Q3TUI adds no instruction of its own about language: the language the LLM writes in is
set by the flow's prompts.

## MCP tools

- **Tools of a step** are written in its `step.py` and given to its LLM when STEP.md lists
  them in `mcp_tools`:

  ```python
  @mcp_tool("smoke_compile", "Compile the testbench with the design; returns the errors")
  async def smoke_compile(self, ctx, args): ...
  ```

  A tool runs with the step's `ctx` (Extensibility), so it can do only what the step may.
- **Built-in tools of Q3TUI**: `tools_available` (which tool roles are available now). The
  filtered `Glob` replaces the built-in one by itself and is not listed. A step without
  code can use only the built-in tools.
- **Outside servers.** The `mcp_servers` of the config are given to the LLM of every step.
  Their tool lists cost tokens in every session, so adding one is your choice. The
  connectors of the claude.ai account are always off, and the user's own Claude Code
  settings and `CLAUDE.md` are never read.

