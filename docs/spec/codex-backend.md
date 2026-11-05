# Codex CLI backend

`llm.backend: codex` (or `q3tui --backend codex …`) runs every LLM stage on the **Codex CLI** (`codex exec --json`) instead of
the Claude Agent SDK. The TUI, the flows, the engine, the questions and the gates are the same; only the agent behind
`q3tui.llm.runtime.run_stage` changes. `claude` stays the default and its code path is untouched.

## Where it plugs in

| | Claude backend | Codex backend (`q3tui/llm/codex/`) |
|---|---|---|
| one query | `claude_agent_sdk.query()` | `runner.query_once`: `codex exec --json … -` (prompt on stdin, cwd = the stage's folder) |
| in-process tools (`mcp__q3tui__*`) | SDK MCP server | `bridge.ToolBridge`: a minimal MCP server (streamable HTTP, JSON) in the Q3TUI process on `127.0.0.1:<port>`, bearer token in `$Q3TUI_MCP_TOKEN`; Codex gets `-c mcp_servers.q3tui.url=…` |
| tool definition | `q3tui.llm.tooldef.tool` → `to_sdk()` | `q3tui.llm.tooldef.tool` → served as it is |
| Read / Grep / Glob / Edit / Write | built-ins + PreToolUse hook | `files.py`: `read_file`, `grep`, `glob`, `write_file`, `edit_file` with the **same** rules (`runtime.guard_reason`) |
| shell / patch tool | not offered to stages | Codex shell off (`features.shell_tool=false`), sandbox `read-only`, approvals `never` |
| structured result | SDK `output_format` | first turn: `--output-schema` (strict form, `runner.strict_schema`, nulls of optional fields dropped by `prune_nulls`); resumed turn: JSON block in the reply (`TEXT_JSON`) |
| session / resume | session id, fork at a message | thread id, `codex exec … resume <id>` |
| cost | USD from the SDK | tokens from `turn.completed`; USD only with `llm.codex.prices` |

Everything else in `runtime.run_stage` is shared: the schema re-ask loop, `LOST_SESSION` handling, `llm_done` / `stats`
events, the stage timeout (the Codex process is killed on cancel), the content-hash of resumable stages
(`pipeline/base.py`, includes the backend).

## Why the file tools are Q3TUI's

Independence (the RTL never sees the testbench, a stage sees only its `Stage.cwd` + `add_dirs`) is enforced for Claude by a hook.
Codex's own shell can read any file, and it has no per-path hook that sees shell commands. So the Codex backend gives the stage
no shell and serves file access itself; each call is checked like the Claude hook. Do not set `llm.codex.shell: true` for
flows that rely on independence.

## Configuration

```yaml
llm:
  backend: codex              # claude (default) | codex
  codex:
    bin: codex                # on Windows prefer the native codex.exe (a .cmd shim mangles the quoted -c values)
    model: null               # null = the Codex CLI's own default; llm.model / llm.steps.<step>.model are Claude ids and are not used
    effort: null              # minimal | low | medium | high | xhigh; a step's effort (llm.steps.<step>.effort) and Stage.effort win; max → xhigh
    sandbox: read-only        # read-only | workspace-write
    extra_args: []            # appended to `codex exec`, e.g. ["--profile", "q3tui"]
    config: {}                # more `-c key=value` overrides, e.g. {"web_search": "disabled"}
    prices:                   # USD per million tokens; "*" = any model. Unset → cost 0, tokens still in `q3tui stats`
      "*": {input: 1.25, cached_input: 0.125, output: 10.0}
    shell: false
```

AGENTS.md of the project folder is not loaded (`project_doc_max_bytes=0`), like `setting_sources=[]` for Claude. Authentication
is Codex's own (`codex login` / `CODEX_API_KEY`).

## Differences you will notice

- **Team mode**: roles keep one persistent thread each, but parallel tasks of a role **queue** (Codex cannot fork a thread at a
  message), and `team.max_context` compaction is skipped (Codex compacts itself).
- A resumed turn asks for its result as a JSON block (no `--output-schema` on resume), validated and re-asked like before.
- `Stage.max_turns` is ignored (as for Claude); `llm.timeout_s` still bounds a stage.
- `thinking` progress events are not emitted.

## Tests

`tests/test_codex_backend.py` runs the backend against `tests/fake_codex.py`, a stand-in that records the command line and
prompt, calls the tool endpoint over HTTP like Codex does, and prints the JSONL events. No test needs a real Codex binary.
**Not yet verified against a real `codex` binary**: the flag placement for `exec resume`, MCP approval behaviour under
`approval_policy=never`, and the exact JSONL fields of newer CLI versions — try `q3tui --backend codex` on `examples/apb_slave`
with `llm.codex.model` set and report anything off.
