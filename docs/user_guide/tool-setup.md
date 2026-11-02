# Setting up the EDA tools for your site

Q3TUI never calls a vendor tool directly: every flow runs a **tool role** (`sim`, `lint`, `cdc`, `fpga_quartus_pro`, …), and a role is a
command you describe for your machine. This page shows where to put yours.

## 1. Start a tools file

In the project folder:

```sh
q3tui tools init      # writes config/tools.json: the roles every built-in flow uses, with plain commands (vcs, dc_shell, vc_static_shell, …)
q3tui tools check     # for the current flow: each role it needs, whether it is configured and its binary is found
```

Q3TUI reads the first tools file it finds:

1. `tools.file` of `q3tui.yaml` (a path; `$VAR` and `~` expand);
2. `<project>/config/tools.json` (or `tools.yaml`);
3. `~/.q3tui/tools.json` (or `$Q3TUI_HOME/tools.json`): **one file for every project on this machine**, used when a project has none.

`tools.roles` in `q3tui.yaml` then overrides single roles of that file.

## 2. Make the tools reachable

Pick what fits your site; they combine.

**On PATH already** (you load your tools in your shell): nothing to do; the default commands (`vcs …`, `vc_static_shell …`) are found on PATH.

**Environment modules**: list them in the tools file, for all roles or per role:

```json
{
  "modules": ["synopsys/vcs", "synopsys/syn"],
  "roles": {
    "fpga_quartus_pro": {"cmd": "quartus_sh -t {script}", "modules": ["quartus/pro"]}
  }
}
```

`modules_init` names the modules init script when it is not `$MODULESHOME/init/bash`.

**A setup script** your site provides: `"setup_script": "/path/to/eda_setup.sh"` (sourced before every tool).

**A given install**: put the full path in the role's `cmd` and the variables the tool needs in its `env`:

```json
{
  "roles": {
    "cdc": {
      "cmd": "/path/to/vc_static/<version>/bin/vc_static_shell -f {script}",
      "env": {"VC_STATIC_HOME": "/path/to/vc_static/<version>"}
    }
  }
}
```

Keep the placeholders (`{script}`, `{files}`, `{workdir}`, …) as the template has them: Q3TUI fills them in.

## 3. Standard-cell libraries (ASIC flow)

The ASIC flow finds the `.db` libraries through a catalog (`q3tui/flows/asic/pdks.json`) whose paths start at **`$PDK_ROOT`**:

```sh
export PDK_ROOT=/path/to/your/pdks     # e.g. $PDK_ROOT/GF180/…, $PDK_ROOT/FreePDK45/…
```

Your own technologies go in `<project>/config/pdks.json` (same format; an entry with the same `id` replaces the built-in one). Or give
the synthesis step its library directly: Settings (`,` on `asic_synth` → Library), or in `q3tui.yaml`:

```yaml
pipeline:
  step_options:
    asic_synth:
      library: $PDK_ROOT/GF180/…/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.db   # one path or a list; ~ and $VAR expand
```

## 4. Tools Q3TUI can find or install

| Tool | How it is found |
|---|---|
| RISC-V GCC, Spike (dv `prepare`) | the roles `riscv_gcc` / `iss` if set, else `$RISCV/bin`, PATH, then `~/.q3tui/tools/{riscv-gcc,spike,dtc}/bin` |
| APB-CSR-Generator (rtl `csr`) | `csr.tool_dir`, `env.CSR_GEN_HOME` of the `csr_gen` role, `$CSR_GEN_HOME`, `~/.q3tui/tools/APB-CSR-Generator` (`q3tui act csr_tool_install` clones it) |
| Verible (rtl `format`, `style_lint`) | `verible-verilog-format` / `verible-verilog-lint` on PATH, or the full path in the roles `verible_format` / `verible_lint` |

## 5. Check it

```sh
q3tui tools check        # ✔ role: binary found · ✖ role: not configured / not found
```

A role that fails at run time (crashed, timed out, not found) stops the step as a **tool failure**, not a design failure: the TUI's
assistant (and an unattended run) is told the error, the role and the machine's memory, and can fix the role's `timeout_s`, `env` or
`modules` itself; what it cannot fix (an install) it tells you.
