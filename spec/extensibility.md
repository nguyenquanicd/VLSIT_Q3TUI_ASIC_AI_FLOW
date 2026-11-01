# Extensibility

Status: **settled**, except the items under "Open items".

How the code that comes with a step extends Q3TUI. What a step declares belongs to Flow
definitions; how it runs to Engine.

## Code of a step

A step has at most two files of code, in its folder (Flow definitions):

|            | `step.py`                                          | `addon.py`                                                    |
| ---------- | -------------------------------------------------- | ------------------------------------------------------------- |
| called by  | the engine, when the step runs                     | you or the assistant, whenever you ask                        |
| does       | the step's own work: tasks, tools, questions, problems handed back | extends Q3TUI: actions (`sdc_set`, `format_now`, …) and log readers           |
| uses       | `ctx`, the narrow API of the running step          | Ops, since an action is a user action like approve            |

The two are kept apart: they run at different times with different rights.

## Steps without code

A step without `step.py` is run by the built-in runner: it runs the step's tasks one after
another (with their `when` and `per_unit`) and writes each task's result to its `to`
output. It does nothing else: logic (branching on a tool's result, reading a tool's
report, deciding what to hand back) is written in `step.py`, not in STEP.md.

## `step.py`

```python
class Step:
    async def run(self, ctx): ...               # required: the step's work
    def check_<name>(self, ctx) -> bool | str:  # optional: the check `code <name>` of `pass`;
        ...                                     #   a string is the reason it does not hold
    def on_approve(self, ctx): ...              # optional: runs when the step is approved

    @mcp_tool("<name>", "<description>")         # optional: an MCP tool of the step (LLM runtime)
    async def <name>(self, ctx, args): ...
```

The step fails when `run` raises; the exception's message is the reason shown.

### `ctx`

What the step reads:

| Member                   | Value                                                             |
| ------------------------ | ----------------------------------------------------------------- |
| `ctx.params`             | the values of the step's params                                   |
| `ctx.inputs[<artifact>]` | the files of an input                                             |
| `ctx.assets[<path>]`     | the file an asset was found at (project first, then home)         |
| `ctx.packages[<name>]`   | the folder of a package                                           |
| `ctx.outputs[<artifact>]`| where an output is written: its file; for a glob, the folder before the first wildcard (`src/rtl/**/*.sv` → `src/rtl/`) |
| `ctx.units`              | the step's units                                                  |
| `ctx.changes`            | what changed since the step last ran (Engine)                     |
| `ctx.settled`            | the settled decisions the step may see (Engine)                   |

What the step does:

| Call                                                       | Does                                                                                         |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `await ctx.task(name, unit=None, **vars)`                  | runs a task declared in STEP.md, in the step's session; `vars` fill the `{{…}}` of its prompt; returns the result (a JSON value for a schema, else text) |
| `await ctx.tool(role, log=None, timeout="broken", **vars)` | runs a tool by a role declared in `tools`; returns its result (Tools / EDA, "Running a role")                                           |
| `ctx.ask(kind, key, text, default, options=None, blocking=False)` | raises a question (Engine, "Questions"); `key` is required; `options` are 0 to 4 choices, each a `text` and its impact |
| `ctx.handback(kind, unit, key, text)`                      | hands a problem back (Engine, "Fix loop")                                                    |
| `ctx.log(message)`, `ctx.warn(message)`                    | writes to the step's log                                                                     |

`ctx` has nothing else: no engine, no state, no config, and no path the step did not
declare. A step can do only what its STEP.md allows.

**Nothing hidden.** What a step must remember from one run to the next (the template it
wrote with, the violations you accepted, what was already tried) is written into one of its
declared outputs, which it reads again in the next run. You can see it, change it and commit
it. A step keeps no state of its own anywhere else.

```yaml
outputs:
  - {artifact: style_waivers, path: "src/rtl/style_lint/waivers.json", mode: seed}
```

```python
async def run(self, ctx):                       # the smoke step
    await ctx.task("smoke_write")
    r = await ctx.tool("sim", tb=ctx.outputs["smoke_tb"])
    if not r.ok:
        verdict = await ctx.task("smoke_triage", log=r.log)
        for f in verdict["failures"]:
            ctx.handback("rtl_fix", f["module"], f["test"], f["summary"])
```

## `addon.py`

```python
def register(api):
    @api.action("sdc_set", "Change one value of the SDC",
                params={"key": "the value's name", "value": "the new value"})
    def sdc_set(ops, key, value) -> str:
        ...                                   # changes files through Ops
        return f"SDC: {key} = {value}"        # one line for the log

    api.parser("vc_static", parse_vc_static)  # a log reader
```

**Actions.**

- Every action is offered in three places: as a tool of the assistant, as a CLI command,
  and as a `/` command of the assistant's chat box (TUI).
- Its params are strings, each with a description; it returns one line for the log.
- An action that changes a file of an output of the step counts as a hand edit (Engine):
  the step gets `edited` and the steps that read that output become stale.
- `api.action(…, confirm=True)` marks an action that destroys something: the assistant
  asks you before it calls it.

**Log readers.** `api.parser(<name>, <function>)` adds a reader of a tool's log (Tools /
EDA).

**Importers.** A step that takes your existing files registers an importer:

```python
api.importer("import_rtl", import_rtl, accepts=["*.sv", "*.v"], doc="your existing RTL")
def import_rtl(ops, files) -> list[str]:    # returns the files it took
    ...
```

An importer is also an action (`/import_rtl path=…`), named by the same rules. Importing a
folder or several files (TUI: File → Import…) offers them to every importer of the flow in
the order of its steps; each takes the files it recognises (by `accepts` and its own
checks), and a file one importer took is not offered to the next. A table then shows which
file went to which step, and which files nobody took.

**Rules.**

- The addons of every step of the flow are loaded when the flow is loaded.
- An action's and a log reader's name are unique in the flow; an action does not take the
  name of an Ops action, and a reader does not take the name of a built-in one; otherwise it is an error when the flow is loaded.

## Loading and validation

- **When.** When Q3TUI opens a project and when the flow is changed, Q3TUI loads the FLOW.md,
  its STAGE.md and STEP.md files (with the lookup of Flow definitions), runs every check
  that Flow definitions states, then imports the `step.py` and `addon.py` files.
- **An unknown key in a flow file is an error** (not a warning as in the config): a
  misspelt key in a definition would make a step run wrongly without anyone knowing.
- **A flow with an error** cannot run. The TUI still opens and shows the list of errors
  (file, key, reason), so that you can fix it or pick another flow; the CLI prints the list
  and exits.
- **Code from the project.** A `step.py` or `addon.py` under `<project>/.q3tui/steps/` is
  loaded only once you allowed it, the same way as a command of the project
  (Configurations): Allow stores its hash in `$Q3TUI_HOME`, and a changed file is asked
  about again. Code from `$Q3TUI_HOME` is not asked about.

## Open items

- View kinds of your own (a step's own UI): later. Until then a step uses the built-in
  kinds of `outputs[].view` (Flow definitions).
