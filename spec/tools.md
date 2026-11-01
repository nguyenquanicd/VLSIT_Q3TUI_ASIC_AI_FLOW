# Tools / EDA

Status: **settled**.

How Q3TUI runs an outside tool for a step: tools are known by **role** (`lint`, `sim`,
`synth`, …), never by binary. The keys that describe a role are in Configurations
(`tools.roles`); which roles a step uses is declared in its STEP.md (Flow definitions).

## Log readers

A role's `parse` names how its log is read into diagnostics.

- Q3TUI's core has readers for common EDA tools: `vcs`, `dc`, `verilator`, `iverilog`,
  `yosys`, `vivado`, `verible`; and `generic`, whose patterns are given in the config:

  ```yaml
  parse: {error: ["^Error-\\[.*\\]"], warning: ["^Warning-"]}
  ```

  `generic` with no patterns (in the config: `parse: generic`) takes a line with the word
  `error` or `fatal` as an error and a line with the word `warning` as a warning, whatever
  their case. Patterns given for a severity replace its default ones.

- A reader for a tool the core does not know is registered by an addon (Extensibility):

  ```python
  api.parser("vc_static", parse_vc_static)
  ```

  Its name is unique and does not take the name of a built-in reader.
- A reader returns diagnostics, each with `severity` (`error` or `warning`), `message`, and
  `file` and `line` when it knows them.

## Presets

A preset is a piece of config (its `tools` section) that starts the role table for a set of
tools. The role names are the flow's (its STEP.md files), so presets come with the flow
repository, as `templates/tools/<name>.yaml`, found by the lookup like any template:

```yaml
# templates/tools/synopsys.yaml
tools:
  modules: [synopsys/vcs, synopsys/syn]
  roles:
    sim:  {cmd: "vcs -full64 -sverilog -top {top} -f {filelist} …", parse: vcs, supports: [sva]}
    lint: {cmd: "vcs … +lint=all …", parse: vcs}
```

- Applying a preset merges it into the **user** layer of the config (tool commands and
  modules belong to the machine). A key you already set is never overwritten. (Where you
  apply one belongs to TUI and CLI.)
- Q3TUI's core ships no preset.

## Running a role

A step runs a role with `ctx.tool(<role>, log=None, timeout="broken", **vars)` (Extensibility).
A step may run several at once (`asyncio.gather`).

- **Environment.** The environment of the tools is made once, when Q3TUI loads (it opens
  the project, or the `tools` section of the config changes), not for each run:
  - `tools.setup_script` is sourced and `tools.modules` are loaded once, and the resulting
    environment variables are kept;
  - a role with its own `modules` gets them loaded once on top of that, kept as the role's
    own environment;
  - a run of a role starts its command directly in the role's kept environment, with the
    role's `env` added.

  A `setup_script` from the project layer is asked about when Q3TUI loads (Configurations,
  "Commands that come with a project"); until it is allowed, nothing is loaded, and every
  role is unavailable with the reason "command not approved".
- **Available.** A role is available when it is configured and the program of its `cmd` is
  found in the `PATH` of its kept environment. A required role that is not available makes
  the step `missing_input` (Engine), with the reason ("`vcs` is not found after loading
  `synopsys/vcs`").
- **Placeholders.** `{project}` (the project root) and `{workdir}` are always there; every
  other one (`{top}`, `{filelist}`, …) is passed by the step in `vars`. A list fills
  several arguments. A placeholder the command needs and nobody gave is an error that names
  the ones available.
- **Working folder.** `.q3tui/state/work/<step>/`: the tool's own files (`csrc/`, `simv`,
  …) go there; a reset of the step deletes it. A file the step wants as an output is
  written where the step says, by passing that path as a placeholder.
- **Log.** `<workdir>/<log>`; `log` defaults to `<role>.log`. A step that runs a role many
  times (one run per test) names each log (`log=f"run_{tc}.log"`).
- **Result.** `ok`, `returncode`, `errors`, `warnings`, the diagnostics, the log's path and
  `timed_out`; or `n/a` when the tool is missing and the step declares it not required. `ok`
  holds when the return code is in `ok_returncodes`, the log has no error and the tool did
  not time out.
- **A broken tool.** When the tool exits with a code not in `ok_returncodes` and its log
  has no error the reader understands, or when it times out with `timeout="broken"` (the
  default), the problem is the tool's
  (its command, environment), not the design's: `ctx.tool` raises and the step
  fails at once, without spending a fix round. The engine does this; the step does not check.
- **A timeout as a result.** With `timeout="result"`, a run that times out returns its
  result (`ok: false`, `timed_out: true`): for a run whose hanging is the design's fault (a
  test that never ends), not the tool's.
- **Progress.** While a role runs, every 60 s Q3TUI writes a `log` event of the step:
  "`<role>`: running <time> — <the last line of its log>", shown in Activities and in the
  step's Log. Nothing more: no reader of progress per tool, no hook for the step.
- **Stop.** When the run is stopped, the tool is killed.

## PDKs and FPGA parts

Q3TUI is a chip design tool: the catalogs of PDKs (`pdks`) and FPGA parts (`fpgas`) are
part of its config (Configurations), shared by the steps of every flow that need them and
by every project of the machine.

- **PDKs.** The corners of a PDK are not stored: they are worked out from the files its
  `globs` match (and `include` keeps).
- **FPGA parts.** Only a part's `title` is stored. The vendor, the family, the tool that
  synthesizes it and the form of the name that tool takes are worked out from the part's
  name by code. The parts Q3TUI knows itself are in code; the parts a spec names are found
  in the spec documents when needed, not stored. The part a run uses is a param of the
  synthesis step, not an entry of `fpgas`.
