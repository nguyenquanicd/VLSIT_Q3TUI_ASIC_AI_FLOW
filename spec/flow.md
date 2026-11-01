# Flow definitions

Status: **settled**.

The content of the files that define a flow: FLOW.md, STAGE.md, STEP.md and SKILL.md. How
a flow runs belongs to Engine; the keys of `config.yaml` to Configurations.

## Where the files come from

The files come from `$Q3TUI_HOME/{flows,stages,steps,skills,templates,rules,knowledge}/`,
where sites (for example a git clone of a flow repository) are linked in; how sites are
installed and linked belongs to Workspace & state ("Sites"). A real folder or file in place
of a link is used the same way (a personal change). The code of a step is in its own
folder, and comes with it.

**Lookup.** A name is looked up in `<project>/.q3tui/` first, then in `$Q3TUI_HOME/`; the
first hit wins.

- `flows/`, `stages/`, `steps/`, `skills/`: a whole folder wins; the two are never mixed.
- `templates/`, `rules/`, `knowledge/`: one file wins over the file of the same path.
- A file shared by several steps is referred to by its name under these folders
  (`rules/rtl_rules.md`) and found by the lookup.

## Keys common to FLOW.md, STAGE.md and STEP.md

| Key           | Required | Rule                                                                         |
| ------------- | -------- | ---------------------------------------------------------------------------- |
| `name`        | yes      | the name of the folder; `snake_case`, at most 64 characters                  |
| `description` | yes      | at most 1024 characters; shown where the flow, stage or step is listed       |
| `version`     | yes      | `MAJOR.MINOR.PATCH` (for example `1.4.2`). For the people who maintain the files: Q3TUI checks its form and shows it, and uses it for nothing else. |

## FLOW.md

```yaml
name: vlsit
description: spec → rtl → verification → sanity → synthesis
version: 1.0.0
stages:
  - spec
  - {use: synthesis, params: {target: fpga}, drop: [asic_synth]}
```

| Key               | Meaning                                                   |
| ----------------- | --------------------------------------------------------- |
| `stages[]`        | the stages, in order: a stage name, or `{use, params, drop}` |
| `stages[].use`    | the stage name                                            |
| `stages[].params` | values of the stage's params in this flow                 |
| `stages[].drop`   | step ids of the stage left out in this flow               |
| `overrides.<id>.gate` | the gate of that instance in this flow                |
| `overrides.<id>.with` | values of that instance's params in this flow         |

- A stage appears at most once in a flow.
- Every use of a step is an instance of its own, with its own state, session, gate and
  params. Its id is its `as`, else the step's name, and is unique in the whole flow: a step
  used twice needs `as` on at least one use.
- An artifact has one producer in a flow (outputs with `mode: update` aside): two instances
  that write the same artifact are an error. (A flow with two stages that both make it
  drops one of them with `drop`.)
- Dropping a step whose output is a required input of another step is an error.
- An `overrides.<id>` whose id is not an instance of the flow is an error.
- Everywhere (FLOW.md, the config, the state), a step is named by its instance id.

The value of a step's param or gate, each later one winning:

```text
param:        STEP params.<name>.default → STAGE steps[].with → FLOW overrides.<id>.with → config steps.<id>.params
stage param:  STAGE params.<name>.default → FLOW stages[].params → config stages.<stage>.params
gate:   STEP gate                  → STAGE steps[].gate → FLOW overrides.<id>.gate → config (Configurations)
```

## STAGE.md

```yaml
name: rtl
description: …
version: 1.0.0
params: {…}
steps:
  - rules
  - {use: rtl_generate, as: rtl, with: {lang: sv}, gate: manual, when: "target == asic"}
```

| Key              | Meaning                                                              |
| ---------------- | -------------------------------------------------------------------- |
| `params.<name>`  | a param of the stage, declared like a param of a step               |
| `steps[]`        | the chain of steps, run in this order: a step name, or `{use, as, with, gate, when}` |
| `steps[].use`    | the step name                                                        |
| `steps[].as`     | the instance id; default: the step name                              |
| `steps[].with`   | values of the step's params; a value may be `"{{<stage param>}}"`, so that a value several steps need is set once, on the stage; when that stage param has no value, the step's param is left unset (its own default applies) |
| `steps[].gate`   | the step's gate in this stage                                        |
| `steps[].when`   | a condition on the stage's params; when false, the step is left out  |

A stage declares nothing else: what it needs, the questions it answers and its actions
are declared by its steps.

### Conditions

Every `when` uses this language, evaluated once, when the flow is loaded:

- a param compared with `==`, `!=` or `in [a, b]`;
- combined with `and`, `or`, `not` and parentheses;
- a param alone means "set and not `false`".

A `when` in STAGE.md (on `steps[]`) uses the stage's params; a `when` in STEP.md uses the
step's params.

## STEP

### The files of a step

```text
steps/<step>/
  STEP.md          required: the declarations, and the prompts of the tasks (its body)
  step.py          optional: the step's code, a class named `Step`
  addon.py         optional: registers the step's actions (Extensibility)
  *.schema.json    optional: JSON Schemas of outputs (`outputs[].schema`) and of task results
  *.py             optional: modules that step.py imports
```

- The names are fixed: a `step.py` is the step's code and an `addon.py` its addon; no key
  of STEP.md names them.
- What several steps share is not here: it is in `templates/`, `rules/`, `knowledge/`
  (declared with `assets`) and `skills/`.
- A structured task result is declared with a JSON Schema, so that a step without code
  can have one.

### Who does what

| From STEP.md                                     | the engine does                                                    |
| ------------------------------------------------ | ------------------------------------------------------------------ |
| `inputs`, `assets`, `outputs`, `params`          | the hash, staleness, `ctx.changes`, the check of required inputs   |
| `tools`, `packages`                              | `missing_input`                                                    |
| `tasks` and the prompts                          | what each task may read and write, its tools, its session, its cost |
| `pass`                                           | the checks after the step ran                                      |
| `gate`, `questions`, `answers`, `handback`, `receives` | the approval, the routing of questions, the fix loop         |
| `outputs[].view`                                 | how the UI shows and reviews an output                             |

`step.py` does only the step's own work, through `ctx` (the full API belongs to
Extensibility):

- `ctx.task(<name>, …)` runs an LLM task declared in STEP.md;
- `ctx.tool(<role>, …)` runs a tool by a role declared in `tools`;
- `ctx.ask(…)` and `ctx.handback(…)` raise a question and hand a problem back;
- it reads `ctx.inputs`, `ctx.params`, `ctx.changes`, and writes `ctx.outputs`;
- a method `check_<name>()` is the check `code <name>` of `pass`.

Rules:

1. Every LLM call is a task declared in STEP.md; the code calls it by name and never makes
   a prompt or grants a tool of its own.
2. The code writes only the declared outputs; the engine checks it.
3. Without `step.py`, a built-in runner runs the tasks in order (with their `when` and
   `per_unit`) and writes their results to the outputs (Extensibility).

### `units`

A step that works by unit (a module, a test case) declares where its units come from:

```yaml
units:
  name: module                                 # what one unit is called
  from: "module_map $.modules[*].name"         # a JSON artifact and the path to the list of names
```

The engine reads the list when the step is about to run, and uses it for:

1. the tasks of the step with `per_unit: true`: one run per unit;
2. a change request aimed at a unit (`[rtl:fifo] …`): a unit that is not in the list is an
   error when the request is made; the request reaches the step in `ctx.changes` with its
   unit;
3. a problem handed back with a unit (`ctx.handback(kind, unit, …)`): the unit is one of the
   **receiving** step's units.

- The artifact may be any artifact the step can see, its own outputs included (a step that
  lists the units it writes: `from: "rtl_plan $.modules[*].name"`).
- When that artifact does not exist (an optional input, an output left out by `when`, or the
  step's own output before its first run), the step has no units: no `per_unit` run, and the
  unit of a request or a problem aimed at it is not checked (there is no list to check it
  against).

### `params`

```yaml
params:
  template:  {type: enum, values: [vlsit, default], default: vlsit, doc: "The spec template"}
  batch:     {type: int, default: 20, affects_result: false, doc: "Findings per review batch"}
  top:       {type: str, required: true, doc: "The top module"}
  rules:     {type: path, doc: "Your rule file"}
```

| Key              | Meaning                                                                                  |
| ---------------- | ---------------------------------------------------------------------------------------- |
| `type`           | required: `str`, `int`, `float`, `bool`, `enum`, `list`, `map` or `path`                 |
| `values`         | the values of an `enum`; required with `enum`                                            |
| `default`        | the default value                                                                        |
| `required`       | the param must have a value (from STAGE, FLOW or the config); not together with `default` |
| `affects_result` | default `true`: the value is in the step's hash. `false` for a knob that does not change the result (a number of turns, a batch size). |
| `doc`            | a description, shown in the settings                                                     |

- A `path` value may be absolute, start with `~`, or hold `$VARIABLES`; a relative one is
  relative to the project root. A `path` param that has a value must name an
  existing file or folder; otherwise the step is `missing_input`. (A `path` param always
  names something the step reads; what it writes is in `outputs`.)
- A param of a stage is declared the same way.
- A value set in the config (`steps.<id>.params`) is checked against the declaration: a
  wrong type or a value outside the `enum` is an error.

### `inputs`

```yaml
inputs:
  - {artifact: spec}                                       # written by another step
  - {artifact: rtl, hashed: false}                         # read, not in the hash
  - {artifact: intent, path: "spec/intent.md"}             # a user file
  - {artifact: spec_refs, path: "spec/ref/*", required: false}
```

| Key        | Meaning                                                                                       |
| ---------- | --------------------------------------------------------------------------------------------- |
| `artifact` | required: the artifact's name                                                                 |
| `path`     | with `path`, a user file (a glob may match several); without it, written by a step of the flow |
| `required` | default `true`; `false`: read when it exists                                                  |
| `hashed`   | default `true`; `false`: read but not in the hash. The step still waits for the step that writes it. |
| `llm_visible` | default `true`; `false`: only the step's code reads it, its LLM tasks never see it (`tb` reading the RTL it tests) |
| `doc`      | a description                                                                                 |

- An input without `path` that no step of the flow writes is an error.
- An input with `path` whose artifact a step of the flow also writes is an error: an
  artifact has one source.

### `assets`

```yaml
assets:
  - rules/rtl_rules.md
  - knowledge/cdc.md
  - templates/{{template}}.yaml    # {{param}}: chosen by a param's value
```

- An asset is a path under `templates/`, `rules/` or `knowledge/`, looked up in
  `<project>/.q3tui/` first, then in `$Q3TUI_HOME/`.
- `{{param}}` picks a file by the value of a param of the step.
- The assets are in the step's hash: a change of one makes the step stale.
- An asset that cannot be found makes the step `missing_input`.
- The LLM tasks of the step may read its assets.

### `outputs`

```yaml
outputs:
  - {artifact: spec, path: "spec/spec.md", user_provided: true}
  - {artifact: rtl, path: "src/rtl/**/*.sv", excludes: [csr_rtl]}
  - {artifact: rtl, mode: update}                         # the format step: rtl changed in place
  - {artifact: rtl_rules, path: "docs/rtl_rules.md", mode: seed}
  - {artifact: smoke_report, path: "reports/smoke.json", schema: smoke.schema.json, when: "enabled"}
```

| Key             | Meaning                                                                                     |
| --------------- | ------------------------------------------------------------------------------------------- |
| `artifact`      | required                                                                                    |
| `path`          | required, except with `mode: update` (the path of the step that creates the artifact is used); a glob may match several files |
| `mode`          | `create` (default): this step creates the artifact. `update`: it changes in place an artifact an earlier step created. `seed`: written the first time only; from then on the file is yours. |
| `user_provided` | `true`: when you placed this file yourself before the step ran, the step is `done` with origin `user` and does not run |
| `schema`        | a JSON Schema of the step's folder; the output is checked against it after every run, and the step fails if it does not match |
| `excludes`      | other artifacts whose files match this `path` and are not part of this one                  |
| `when`          | a condition on the step's params; when false, the step has no such output                  |
| `view`          | how the UI shows and reviews the output (below)                                             |

- A step that reads an artifact depends on the step that creates it and on every other
  step that updates it.
- An output with `mode: seed` is never deleted by a reset, and once written the step never
  overwrites it. From then on it is also an input of the step itself, in its hash: when you
  edit it, the step is stale and runs again as an update (the `sdc` step renders `sdc.tcl`
  again from your `sdc.json`).

### `outputs[].view`

```yaml
view: {kind: sections, template: "templates/{{template}}.yaml", review: true}
view:
  kind: table
  rows: "$.requirements"           # the path to an array (or an object) in the JSON file
  id: req_id                       # the field that names a row
  columns: [req_id, {field: text, title: Requirement}, state]
  detail: [text, source]           # the fields shown in the detail pane
  state: {field: state, map: {approved: ok, review: warn}}   # shown as ok | warn | error | todo
  review: true
```

| `kind`     | For                                        | Its keys                                    |
| ---------- | ------------------------------------------ | ------------------------------------------- |
| `document` | one file, rendered to read                 |                                             |
| `files`    | several files, one picked to read          |                                             |
| `sections` | a Markdown file in sections, one row each  | `template`, `by` (`marker` or `heading`)    |
| `table`    | a JSON file, one row per element           | `rows`, `id`, `columns`, `detail`, `state`  |

Every kind takes `title` (its label); `sections` and `table` also take `review`.

- `sections` with `by: marker` (the default): a section starts at a line
  `<!-- section: <id> -->` and runs to the next such line. With `by: heading`: a section
  starts at a `## <title>` line, whose title is its id, and runs to the next one.

- Without `view`, the UI picks `document` for a path that names one file and `files` for a
  glob.
- `state` maps a row's field to its mark; a field that is a boolean or a number is matched by
  its JSON text (`true`, `false`, `0.3`), so `{"true": warn}` and `{true: warn}` both match.
- `review: true` (only with `sections` and `table`): each section or row is a review item
  (Engine, "Gates").
- These four kinds are the only ones (a kind of your own is an open item of Extensibility).
- Each output with a view is one tab in the UI, in the order of `outputs`.

### `tools` and `packages`

```yaml
tools:
  - {role: sim, required: true}
  - {role: csr_gen, required: "mode != off"}        # a condition on the step's params
packages:
  - name: apb-csr-generator
    source: {git: "https://…/APB-CSR-Generator.git", ref: v1.2}
    must_contain: [CSR_Generation.py]
    required: true
```

`tools[]`: tools run by role (their commands are in `tools.roles` of the config).

| Key        | Meaning                                                                                       |
| ---------- | --------------------------------------------------------------------------------------------- |
| `role`     | the role                                                                                      |
| `required` | `true` (default), `false`, or a condition on the step's params. A missing required tool makes the step `missing_input`; a check `tool` on a missing tool that is not required is N/A, never a pass. |
| `doc`      | a description                                                                                 |

`packages[]`: folders or software from outside that the step uses directly, not through a
role.

| Key            | Meaning                                                                   |
| -------------- | ------------------------------------------------------------------------- |
| `name`         | the package's name                                                        |
| `source`       | where it is downloaded from: `{git, ref}`; `ref` is a tag or a commit, never a branch |
| `must_contain` | files that must be in the package's folder                                |
| `required`     | `true` (default), `false`, or a condition on the step's params; a missing required package makes the step `missing_input` |
| `doc`          | a description                                                             |

- A package is found at `<project>/.q3tui/packages/<name>`, then at
  `$Q3TUI_HOME/packages/<name>`.
- A package is installed as a site (Workspace & state, "Sites"), linked as
  `$Q3TUI_HOME/packages/<name>`. A package installed elsewhere is used by making that link
  point to it.
- The step's code gets the package's folder as `ctx.packages[<name>]`.
- A package is downloaded only when you ask for it. A required package that is missing
  makes the step `missing_input`, with an [Install] button in the TUI (the CLI says how to
  install it); before downloading, Q3TUI shows the `source`. Nothing is ever downloaded on
  its own, `unattended` included.
- Q3TUI records the `ref` it installed. When the STEP.md asks for another `ref`, the step is
  `missing_input` ("the package is at `v1.2`, the step needs `v1.3`"), with an [Update]
  button, also run only when you ask.

### `pass`

The step's definition of done, checked by the engine whatever the step's code does: it
lets a step without code be checked, a team add its own criteria without changing code,
and a reader see what "done" means; the engine also runs it for a rebase (Engine).

```yaml
pass:
  - {check: "tool lint errors == 0 and warnings <= max_warnings", on_fail: fail}
  - {check: "json smoke_report $.failed length == 0", on_fail: fail}
  - {check: "contains spec TBD", on_fail: warn, when: "strict"}
  - {check: "code all_modules_written", on_fail: fail}
```

| Key       | Meaning                                                  |
| --------- | -------------------------------------------------------- |
| `check`   | required: one check (below)                              |
| `on_fail` | `fail` (default): the step fails. `warn`: a warning only. |
| `when`    | a condition on the step's params                         |
| `doc`     | a description                                            |

| Check                                                    | Holds when                                                                  |
| -------------------------------------------------------- | --------------------------------------------------------------------------- |
| `exists <artifact>`                                      | the artifact is on disk                                                     |
| `contains <artifact> <regex>`                            | a file of the artifact matches the regex                                    |
| `json <artifact> <$.path> [length] <op> <value or param>` | a field of the JSON file compares true; `op` is `==`, `!=`, `>=`, `<=`, `>` or `<` |
| `tool <role> <expression>`                               | the expression holds on the step's last run of that tool (`ok`, `errors`, `warnings`) and its params; N/A when the tool is missing and not required |
| `code <name>`                                            | the method `check_<name>()` of `step.py` says it holds                      |
| `run <command>`                                          | the shell command exits with 0                                              |

- The checks run in order after the step ran, before its gate, but only in a run where the
  step handed no problem back. A run that hands problems back is a round of the fix loop
  (Engine): its checks are not run, and the loop takes over. So a check "no problem left"
  is not needed on a checking step; `pass` states the rest (a report exists, a figure is
  within its limit).
- A `run` check of a STEP.md from the project (`<project>/.q3tui/steps/`) is asked about
  before it runs, like a command of the project's config (Configurations).

### `gate`, `questions`, `answers`, `handback`, `receives`

What they do belongs to Engine ("Gates", "Questions", "Fix loop").

```yaml
gate: auto                 # manual, auto or unattended; default auto
questions: [spec_gap]      # the kinds of question the step may ask
answers:   [arch_gap]      # the kinds of question whose answers the step owns
handback:  [rtl_fix]       # the kinds of problem the step may hand back
receives:  [style_fix]     # the kinds of problem the step fixes
```

- Every question is asked of you; its kind only says where the answer goes.
  `design_choice` (a decision that belongs to the asking step itself, which the earlier
  steps rightly leave open) may always be asked, is never listed in `questions`, and no step
  `answers` it.
- A step that asks a kind not in its `questions`, or hands back a kind not in its
  `handback`, fails (an error of the step).
- When the flow is loaded:
  - a kind has at most one step that `answers` it and at most one that `receives` it;
  - every kind in a `handback` has exactly one step that `receives` it, and that step is
    one the handing step depends on; otherwise it is an error.

### What the LLM may read

The LLM tasks of a step may read only what the step declares:

- its `inputs`, except those with `llm_visible: false`;
- its `assets`;
- its own `outputs`;
- its `skills`;
- the files and folders its `path` params name;
- its `packages`.

Nothing else of the project; and never `.q3tui/state/`, even if a declaration points
into it.

**Who sees whose decisions.** A step receives the settled decisions (Engine, "Questions") of
the steps whose outputs its LLM may read, directly or through other steps; never of the
others.

### `skills`, LLM tools and `tasks`

```yaml
skills: [smoke-testbench]              # skills the step's LLM may read
llm_tools: [Read, Grep, Glob, Write]   # built-in tools of the step's LLM, for every task
mcp_tools: [smoke_compile]             # Q3TUI's own tools, for every task
write: [smoke_tb]                      # the outputs (by artifact) the LLM may write
tasks:
  - name: smoke_write                  # its prompt is the section of the same name
    output: markdown
  - name: smoke_triage
    output: triage.schema.json
    to: smoke_verdict                  # (no step.py) the output that receives the result
    per_unit: true
    when: "enabled"
```

| Key                | Meaning                                                                               |
| ------------------ | ------------------------------------------------------------------------------------- |
| `skills`           | the skills the step's LLM may read; `skills/<name>/SKILL.md`, found by the lookup      |
| `llm_tools`        | the built-in tools of the step's LLM: `Read`, `Grep`, `Glob`, `Write`, `Edit`; default none |
| `mcp_tools`        | MCP tools given to the step's LLM: the step's own (`step.py`) or Q3TUI's built-in ones (LLM runtime) |
| `write`            | the outputs (by artifact) the LLM may write; required with `Write` or `Edit`           |
| `tasks[].name`     | required: the task's name, used by `ctx.task(<name>)`, in the log and in the cost; its prompt is the section of the body with the same name |
| `tasks[].output`   | the form of the result: a JSON Schema file of the step's folder, `markdown` or `text` |
| `tasks[].to`       | the output that receives the result; used only by a step without `step.py`           |
| `tasks[].per_unit` | one run per unit, one after another                                                   |
| `tasks[].when`     | a condition on the step's params                                                      |

- The names of the LLM's built-in tools are written as Claude names them (`Read`, `Grep`,
  `Glob`, `Write`, `Edit`), as in a SKILL.md's `allowed-tools`. Every other value that
  Q3TUI defines is written in lower case.
- The LLM tools, the MCP tools and what may be written belong to the step, not to a task:
  every task of a step runs in its one session with the same tools. Work that must not
  have them is a step of its own.

## SKILL.md

SKILL.md follows the Agent Skills standard.

## Body of the files

| File     | Body     | What it is                                                                                      |
| -------- | -------- | ----------------------------------------------------------------------------------------------- |
| FLOW.md  | optional | documentation for people (the UI shows it with the flow; the assistant may read it); the engine does not use it |
| STAGE.md | required when a step of the stage has tasks | one section `SYSTEM PROMPT`: the system prompt of the sessions of the stage's steps (LLM runtime) |
| STEP.md  | required when the step has tasks | one section per task, named after the task: the task's prompt, sent as a message in the step's session |

A section is written

```markdown
<!-- smoke_write -->
Write the smoke testbench of module {{module}}…
<!-- /smoke_write -->
```

- Every task has exactly one section of its name, and every section of a STEP.md belongs
  to one task. A STAGE.md has at most one section, `SYSTEM PROMPT`, and has it when a step
  of the stage has tasks. Otherwise the body is optional.
- Only `<!-- <task name> -->` (in STEP.md) and `<!-- SYSTEM PROMPT -->` (in STAGE.md), with
  their closing lines, mark sections. Any other HTML comment is plain text of the prompt
  (for example the section markers of a spec document, `<!-- section: interfaces -->`,
  that a prompt shows the LLM how to write).
- What is outside the sections is documentation for people; it is never sent to the LLM.
- **Placeholders** are written `{{name}}`, where the name is letters, digits and `_`. A
  single `{…}` is always plain text (SystemVerilog `{a, b}`, a glob `{a,b}`, JSON), and so
  is `{{` not followed by a single name (`{{8{1'b0}}}`). Their sources and where they may
  be used:

  | Source                                                   | Example      | Used in                                                              |
  | -------------------------------------------------------- | ------------ | -------------------------------------------------------------------- |
  | a param of the step (of the stage, in STAGE.md)          | `{{template}}` | prompts, the `artifact` and `path` of `inputs` and `outputs`, `write`, the artifact named by a `pass` check, `assets`, `view.template` |
  | a param of the stage                                     | `{{part}}`     | the values of `steps[].with` in STAGE.md |
  | the unit being run, named after `units.name`             | `{{module}}`   | the prompt of a `per_unit` task                                      |
  | a variable passed by `ctx.task(<name>, **vars)`          | `{{log}}`      | prompts                                                              |

  They are allowed nowhere else. A placeholder that has no value where it is used is an
  error that names it. In an artifact's name, the placeholder is replaced when the flow is
  loaded, from the params of the instance (`{{role}}_report` gives `cdc_report` and
  `rdc_report` for two instances of one step), and every rule about artifacts applies to the
  names it gives.
