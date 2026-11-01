# Configurations

Status: **settled**.

The settings of Q3TUI: where they are, how the layers merge, and every key. What a key
does belongs to the aspect that uses it (for example the gate modes to Engine); this file
owns the key's name, type, range and default.

## Layers

From lowest to highest; a higher layer wins: session > project > user > default.

| Layer   | Set by                                                                 | Lasts                                                   |
| ------- | ---------------------------------------------------------------------- | ------------------------------------------------------- |
| default | this spec                                                              | always                                                  |
| user    | `$Q3TUI_HOME/config.yaml` (default `~/.q3tui`): yours, on this machine; not committed | until changed                     |
| project | `<project>/.q3tui/config.yaml`: the project's, shared with its team; committed | until changed                             |
| session | `--config key=value` when Q3TUI starts, and the menus of the title bar | until Q3TUI exits; never written to a file              |

- `--config` takes a dotted key and a value read as YAML, and can be given several times:
  `--config llm.model=claude-opus-5-5 --config pipeline.max_fix_rounds=8`.
- **Order before key.** Where two keys decide the same thing (`steps.<step>.gate` and
  `pipeline.gate_mode`), the value comes from the highest layer that sets either of them;
  inside one layer the more specific key (`steps.<step>.…`) wins.

## Where Q3TUI writes

| What                                                                          | Layer                               |
| ----------------------------------------------------------------------------- | ----------------------------------- |
| a menu of the title bar (model, effort, flow, gate mode, …)                   | session                             |
| a menu of the Flow tree (the gate of one step)                                | session                             |
| the assistant's `set_gate_mode` and, by default, its `set_settings`            | session                             |
| the settings screen                                                           | session, project or user: the tab that is open |
| an action of a flow that saves what belongs to this machine (a tool command, a PDK path) | user                     |
| an action of a flow that saves what belongs to the design (the part in use, a param)     | project                  |

- The session layer lives only in memory: it is never written to a file.
- The gate of one step is kept beyond a session by the flow editor (TUI, Open items).
- **Reset** on the settings screen removes the key from that tab's file, so the lower
  layer shows through again; it does not write `null`.
- Writing a file keeps its comments, key order and layout. A file that would not read back
  is not written.

## Merge rules

One rule set for every key and every layer, `--config` included.

| Value in the higher layer     | Result                                                   |
| ----------------------------- | -------------------------------------------------------- |
| map                           | merged key by key, recursively                           |
| number, string, bool          | replaces                                                 |
| list                          | replaces the whole list (no append)                      |
| `null`                        | removes the key, with what the lower layers set          |

- Anything a user may add to or change one entry of is a **map keyed by name**, never a
  list (`tools.roles`, `pdks`, `fpgas`).
- An empty value (`key:`) is `null` in YAML, so it removes the key. Q3TUI warns when it
  sees one.

```yaml
# user                              # project                  # result
pdks: {gf180: {…}, freepdk45: {…}}  pdks: {freepdk45: null}    pdks: {gf180: {…}}
```

## Validation

Every layer is checked when Q3TUI starts, `--config` included, and every entry of a map
(`tools.roles`, `pdks`, `fpgas`) against its own keys.

| Case                                                     | What happens                                                                                     |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| a file that is not valid YAML                            | error before the TUI appears: the file, the line and the reason are printed, and Q3TUI exits      |
| a value of the wrong type or out of range, in any layer  | error before the TUI appears, as above                                                           |
| an unknown key                                           | warning with the closest known key (`llm.modle`: did you mean `model`?); the key is ignored and Q3TUI goes on. The CLI prints it; the TUI shows it when it opens. |

The TUI never opens with a config that has an error.

## Defaults and installation

- The default of every key is the one this spec gives. The code uses exactly these values.
- Installing Q3TUI creates `$Q3TUI_HOME/config.yaml` when it does not exist, with three
  keys: `llm.model`, `llm.effort` and `pipeline.flow`, set to their defaults. An existing
  file is never overwritten.
- Installing Q3TUI also installs the site of the default flow (Workspace & state, "Sites"),
  when it is not installed: `vlsit`, from
  `https://github.com/nguyenquanicd/VLSIT_Q3CORE_ASIC_AI_FLOW`, at the newest tag of that
  repository (by version order) at the time of installing; `sites.yaml` records that tag.
  A site already installed is kept as it is: updating it is asked for (Settings, [Update]).
  When the site cannot be downloaded (no network, no tag yet), installing goes on and says
  so, with how to install it later.
- Everything else (tools, PDKs, FPGA parts, …) is set up by the user.
- The keys written at installation are the user's from then on: a later version of Q3TUI
  with another default does not change them.

## Sections

| Section       | What it holds                                                  |
| ------------- | -------------------------------------------------------------- |
| `llm`         | the LLM settings of the whole project                          |
| `pipeline`    | the engine settings of the whole project                       |
| `steps`       | per step: `steps.<step>.{gate, model, effort, params}`          |
| `stages`      | per stage: `stages.<stage>.params`                             |
| `tools`       | how tools run, and the tool roles                              |
| `pdks`        | the standard-cell libraries of the ASIC flow                   |
| `fpgas`       | the FPGA parts you add                                         |
| `mcp_servers` | outside MCP servers given to the LLM                           |
| `tui`         | how the TUI looks                                              |

`<step>` is always the instance id of a step (Flow definitions). Everything about one step
is under `steps.<step>`, and about one stage under
`stages.<stage>`; no other section names a step or a stage. `params` are the values of
the params the STEP.md or STAGE.md declares.

```yaml
steps:
  rtl:
    gate: manual
    model: claude-opus-5-5
    effort: high
    params: {lang: sv}
stages:
  synthesis:
    params: {target: asic}
```

**Values, not structure.** The config sets values (a param, a gate, a model, a tool
command). The structure of a step or a stage (its inputs, outputs, checks, prompts,
steps) is changed in its file (Flow definitions), never in the config.

### `llm`

What each key does belongs to LLM runtime.

| Key                 | Type                                             | Default             | Meaning                                                           |
| ------------------- | ------------------------------------------------ | ------------------- | ----------------------------------------------------------------- |
| `model`             | string                                           | `claude-sonnet-5-5` | the model of every LLM task                                       |
| `fallback_model`    | string or null                                   | null                | the model used when the main one fails                            |
| `effort`            | `low`, `medium`, `high`, `xhigh`, `max`, or null | `medium`            | null for a model without effort (Haiku 4.5)                       |
| `thinking_budget`   | integer ≥ 0, or null                             | 6000                | the thinking tokens of a model without effort; 0 = no thinking    |
| `timeout_s`         | integer ≥ 1, or null                             | null                | the longest one LLM task may take; null = no limit                |
| `task_max_cost`     | number > 0 (USD), or null                        | null                | the most one LLM task may spend; null = no limit                  |
| `tool_output_limit` | integer ≥ 500                                    | 6000                | the most characters one tool call returns                         |
| `task_token_budget` | integer ≥ 10 000, or null                        | 1 000 000           | warn when one task reads more input tokens than this              |
| `env`               | map of string to string                          | `{}`                | environment variables given to the LLM                            |

### `pipeline`

What each key does belongs to Engine.

| Key                    | Type                                     | Default | Meaning                                                        |
| ---------------------- | ---------------------------------------- | ------- | -------------------------------------------------------------- |
| `flow`                 | string                                   | `vlsit` | the flow a run uses                                            |
| `gate_mode`            | `manual`, `auto`, `unattended`, or null  | null    | the gate mode of every step; null = the flow files decide      |
| `auto_confirm_reviews` | bool                                     | false   | confirm every review item                                      |
| `max_fix_rounds`       | integer 1–20                             | 5       | the most rounds of a fix loop                                  |
| `max_parallel_stage`   | integer ≥ 1                              | 1       | the most stages that run at the same time                      |
| `max_cost`             | number > 0 (USD), or null                | null    | the most one run may spend; null = no limit                    |

### `steps` and `stages`

| Key                             | Type                                      | When not set                                                       |
| ------------------------------- | ----------------------------------------- | ------------------------------------------------------------------ |
| `steps.<step>.gate`             | `manual`, `auto`, `unattended`            | the flow files                                                     |
| `steps.<step>.model`            | string                                    | `llm.model`                                                        |
| `steps.<step>.effort`           | `low`, `medium`, `high`, `xhigh`, `max`   | `llm.effort`; ignored for a model without effort (Haiku 4.5)       |
| `steps.<step>.params.<param>`   | as the STEP.md declares the param         | the STEP.md's default                                              |
| `stages.<stage>.params.<param>` | as the STAGE.md declares the param        | the STAGE.md's default                                             |

- A `<step>` or `<stage>` that no flow Q3TUI can find has is a warning (an unknown key).
  One that belongs to another flow than `pipeline.flow` is not.
- A param that the STEP.md or STAGE.md does not declare is a warning; a value of the
  wrong type or outside its enum is an error.

### `tools`

What each key does belongs to Tools / EDA.

```yaml
tools:
  timeout_s: 600          # integer ≥ 1: the longest one tool run may take, in seconds
  modules: []             # list of string: loaded once when Q3TUI loads, for every tool
  modules_init: null      # string or null: the module init script; null = $MODULESHOME/init/bash
  setup_script: null      # string or null: a script sourced once when Q3TUI loads, for every tool
  roles:                  # map: role name -> how to run it
    <role>:
      cmd: "..."          # string, required: the command, with placeholders
      parse: generic      # the name of a log reader, or {error: [regex], warning: [regex]}
      description: ""     # string: shown to the LLM task that may run it
      cwd: null           # string or null: null = the tool's working folder (.q3tui/state/work/<step>/)
      timeout_s: null     # integer ≥ 1, or null: null = tools.timeout_s
      env: {}             # map of string to string
      modules: []         # list of string: loaded once on top of tools.modules, for this role
      ok_returncodes: [0] # list of integer
      supports: []        # list of string: capabilities (for example sva); a missing one is reported N/A
```

### `pdks`


```yaml
pdks:                     # map: PDK id -> its entry; null hides an entry of a lower layer
  <id>:
    title: "..."          # string, required
    node_nm: 180          # integer ≥ 1, required
    foundry: ""           # string
    globs: ["..."]        # list of glob, required: the .db files
    include: null         # regex or null: a file name must match it; null = every file
    default_corner: null  # string or null: the corner picked with the technology
    probe_ns: 1.0         # number > 0: the clock period the quick Fmax estimate starts from
```

What the entries mean belongs to Tools / EDA.

### `fpgas`


```yaml
fpgas:                    # map: part -> its entry; only the parts you add; null hides a part of a lower layer
  <part>:
    title: "..."          # string
```

What the entries mean belongs to Tools / EDA.

### `mcp_servers`

They are given to the LLM of every step (LLM runtime).

```yaml
mcp_servers:              # map: name -> server; null hides a server of a lower layer
  <name>:
    type: http            # http, sse or stdio; required
    url: "..."            # string: required for http and sse
    headers: {}           # map of string to string: http and sse
    command: "..."        # string: required for stdio
    args: []              # list of string: stdio
    env: {}               # map of string to string: stdio
```

### `tui`

What each key does belongs to TUI.

| Key     | Type                | Default      | Meaning                          |
| ------- | ------------------- | ------------ | -------------------------------- |
| `theme` | `vlsit-dark`        | `vlsit-dark` | the theme (there is one)         |
| `icons` | `nerd` or `unicode` | `nerd`       | the icon set: Nerd Font glyphs, or plain Unicode for any font |

## Commands that come with a project

A project's `config.yaml` can carry shell commands (`tools.roles.<role>.cmd`,
`tools.setup_script`, `mcp_servers.<name>.command`), and so can a STEP.md in the project's
`.q3tui/steps/` (a `run` check, Flow definitions); a project you cloned is somebody
else's. All of them are treated the same way, and so is the code of a step that comes
with the project (Extensibility).

- The first time a command from the **project** layer is about to run, Q3TUI asks:
  "This project wants to run: `<command>`" [Allow] [Deny].
  - **Allow** stores the command's hash in `$Q3TUI_HOME`. The same command is not asked
    about again; a changed command is.
  - **Deny**: the step does not run and reports "command not approved".
- Commands from the user and session layers are not asked about.
- Without anyone to ask (the CLI), a command that is not approved does not run; the step
  reports "command not approved" and says how to approve it.
- The gate mode `unattended` never approves a command.
