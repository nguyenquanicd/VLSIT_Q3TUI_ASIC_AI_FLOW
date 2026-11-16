# The ASIC flow (`asic`) — synthesis to a standard-cell netlist and its equivalence check

A built-in folder flow (`q3tui/flows/asic/`, `pipeline.flow: asic` or `q3tui --flow asic`) that takes the RTL the rtl flow produced
(`src/rtl/`, read only), synthesizes it with Design Compiler to a standard-cell library, and proves the netlist equal to the RTL with
Formality. It is the "ASIC synthesis" box of the flow map (ASIC port → ASIC synthesis → LEC). The spec and rtl flows are untouched; the flows
share `constraints/sdc/` (the same files the FPGA flow writes) and hand work to each other through change requests.

```
sdc ─► asic_port [gate: human] ─► asic_macro [gate: human] ─► asic_synth [gate: human] ─► asic_lec [gate: human]
```

The SDC comes first: its clock decides which memory macros are fast enough and goes to a memory compiler that takes one.

| Step | Kind | Does | Writes |
|---|---|---|---|
| `sdc` | `asic.sdc` | the FPGA flow's SDC step: `constraints/sdc/sdc.json` → `constraints/sdc/*.tcl` | `constraints/sdc/*.tcl` |
| `asic_port` | `asic.asic_port` | code scan of `src/rtl/` for what an ASIC cannot take, then the porter (one read-only LLM stage, `rules/asic_port_rules.md`): the porting work the scan cannot do (SRAM wrappers, synchronizer cells, ICGs, …) as work orders for the RTL | `schemas/asic_port.json` |
| `asic_macro` | `asic.asic_macro` | the memory wrappers (`*_sram` / `*_rf` / `*_rom`) as memory macros of the PDK: a memory compiler (tool role `mem_compile`), else a tiling of pre-generated macros, else flip-flops; the ASIC body by code, `.lib` → `.db` (tool role `lib_compile`), a lock-step check against the behavioural wrapper (tool roles `sim` + `run`) | `build/syn/asic/macros/<wrapper>.sv`, `build/syn/asic/macros/db/*.db`, `schemas/asic_macro.json` |
| `asic_synth` | `asic.asic_synth` | Tcl script (code) + tool role `asic_synth` (`dc_shell -f`): compile, netlist, reports, numbers against targets | `build/syn/asic/synth.tcl`, `build/syn/asic/netlist/<top>.{v,ddc,sdc,svf}`, `build/syn/asic/reports/*.rpt`, `schemas/asic_synth.json` |
| `asic_lec` | `asic.asic_lec` | Tcl script (code) + tool role `asic_lec` (`fm_shell -f`): RTL vs netlist | `build/syn/asic/lec.tcl`, `build/syn/asic/reports/lec.rpt`, `schemas/asic_lec.json` |

Top module: `options.top` or `schemas/structured_spec.json` `metadata.top_module`; file list: `src/rtl/filelist.f`. A missing tool or library
fails the step ("not run"), never passes it.

## ASIC port (`asic_port`)

Two parts. **The scan** is deterministic and ground truth (comments and `// synopsys translate_off` regions skipped); each finding has an id
(`P1`…), the rule, the module, the line, the code, the fix that belongs to it and `source: code`:

| Rule | Severity | Finds |
|---|---|---|
| `vendor_primitive` | error | instantiated FPGA primitives (`xpm_*`, `RAMB*`, `DSP48*`, `BUFG`, `FDRE`, `LUT6`, `altsyncram`, …) |
| `sim_only` | error | `$display`, `$finish`, `$random`, `#delays`, `force` / `release`, `fork`, `wait` |
| `fpga_attribute` | warn | `ram_style`, `use_dsp`, `keep`, `mark_debug`, `async_reg`, `max_fanout`, `syn_*`, … |
| `memory_array` | warn | unpacked arrays of `min_mem_words` or more (default 16) — flip-flops in standard cells; wants an SRAM / register-file macro |
| `mem_init` | warn | `$readmem[hb]` |
| `initial_value` | warn | `initial` blocks and declaration initialisers (no power-up value in an ASIC) |
| `tristate` | warn | `'z` drivers |
| `gated_clock` | warn | a clock assigned from logic |

**The porter** is one read-only LLM stage (`Read`, `Grep`, `Glob`; the testbench, SVA and models denied) that reads the RTL with the rule
files of `options.rules` (default `asic_port_rules.md`, in the step's `rules/`; a project path wins) and does the porting the scan cannot do:
it decides what changes, which wrapper replaces what and with which ports, and writes that as work orders (findings with `source: llm`, a
`wrapper` module and a `fix` the RTL author can write without asking). The rule file has the wrapper convention (a structure a macro or a library cell implements sits behind one small
`m_<function>` module with fixed ports), the scan's rules (not reported again) and the port rules: `mem_sram_wrapper` (memories →
SRAM / register-file / ROM wrappers), `sync_lib_cell` (synchronizers → library cells behind `m_sync_*`), `clock_gate_icg`,
`clock_mux_divider`, `pll_macro_wrapper`, `pad_wrapper`, `latch_inferred`, `async_reset_style`, `fpga_only_branch`. Code checks the answer:
an unknown rule id, an unknown module or a waived rule is dropped (and said in `dropped`), and an order at a line the scan already has becomes that finding's port (its `wrapper` and `fix` replace the scan's generic fix, kept as
`scan_fix`), not a second finding. The porter follows "changes propagate as updates": `asic_port.json` records each file's hash and the rules / options key,
and only the files whose text changed (or all of them, when a rule file or option changed) go back to the LLM; the others keep their findings.
`options.port: false` runs the scan only. The step writes no RTL: the RTL is the rtl flow's, so the orders go there (`asic_handoff`) and its rtl step writes the ported code.

The gate is your review. `options.waive: [rule ids]` ignores rules (both parts), `options.min_mem_words` sets the memory threshold. **Hand-off**
(`asic_handoff`, the Findings tab's `h` / `H` — they also move the TUI to that flow, `q3tui act asic_handoff [ids=P1,P2]`, the
assistant): every finding goes to the flow that owns the RTL (`options.handoff_flow`, default `rtl`). An order with a `wrapper` adds a module
to the design, which only the spec can do (parse puts it in the structured spec, the rtl step's plan then writes its file and the parent
instantiates it): all of them go to that flow's `spec` step as one change request (`port.spec_text`: the wrapper, its parent, its function,
ports and latency — no macro or technology). The rest are changes in place: a scoped change request of its `rtl` step each,
`[rtl:<module>] ASIC port (<file>:<line>, <rule title>): <code> — <fix>` (`port.handoff_step` picks). Run that flow to apply them; this flow's steps are then stale and run again.
Unattended (`pipeline.auto_answer`, the gate's mode `auto_answer`, `q3tui auto`) the step does it itself: it hands off every error and every
finding the porter wrote an order for, runs the owner flow from `spec` when a wrapper went there, else from `rtl` (… → rtl → format → style_lint → smoke), and the asic flow runs again on the
new RTL; a scan warning the porter left without an order (it saw nothing to port, e.g. a wire array) stays for you. A finding is sent once.
The scan does not report the array inside a memory wrapper (`*_sram` / `*_rf` / `*_rom`): that is where the macro goes. `asic` is not in the
default `pipeline.chain`; add it after `fpga` to have `q3tui auto` run it (it then counts as a checking flow: an RTL change it makes runs dv,
sanity and fpga again).

## Memory macros (`asic_macro`)

Code in `lib/macro.py`, the step in `asic_macro/step.py`, its stage prompts in `asic_macro/md/skill.md` (`SPEC`, `PINS`, `COMPILER`). TUI: the step's **Macros** tab (`panels.py`): one row per wrapper — how (macros / compiled / flops), the macro, the grid, the area, the check — and, for the highlighted one, its memory, the PDK, corner and clock, the files, why the others were not taken and the compiler's verdict.

- **Wrappers.** The modules of `src/rtl/` named like the port rule file's memory wrappers (`*_sram`, `*_rf`, `*_rom`). Their ports and
  widths as instantiated come from the elaborated design (pyslang); what the memory is — words, bits, each access port (rw / r / w: clock,
  address, data, enable, write enable, byte enables and polarities), the read latency — from a read-only LLM stage (`MemSpec`), checked
  by code against those ports (`spec_problems`: the names exist, the words fit the address, the data widths match).
- **The PDK.** `options.pdk_root`, or the parent of the `asic_synth` library that has a memory folder (`MEMORY`, `SRAM`, …). The corner is
  `options.corner` or the library's (`…tt0p9v25c.db` → `tt0p9v25c`). Code walks the memory folders: every Liberty file with a
  `memory ()` group is a macro (cell, words, bits, address bits, area), one file per cell — the corner's when there is one — with its
  Verilog model and LEF; the catalog is cached in `.q3tui/asic/asic_macro/catalog.json`. Executables under a `Compiler` folder are the
  memory compilers.
- **A compiler** (`options.prefer: compiler`, the default) is judged by a read-only LLM stage that reads its kit (`CompilerPlan`: usable or
  what is missing; the command, the input file for this memory with the clock target, where the views land). It runs only as the tool role
  `mem_compile` of `config/tools.json`; without that role the proposal is recorded (`compiler` in the JSON, a warning) and the step goes on
  with the macros.
- **Pre-generated macros.** Code ranks the tilings (rows × columns of one macro for the words × bits) by total area, then fewer macros;
  a macro whose words are not a power of two can only be one row. For the 12 smallest, the macro's Liberty pins and the `minimum_period` of
  its clock pin are read; a macro slower than the fastest SDC clock (its ASIC frequency) is out. The pins of a macro family (one map per
  set of pin names) come from a read-only LLM stage that reads the Verilog model (`PinMap`: the functional ports, the polarities, every
  other input tied to its normal-operation constant), checked by code (`pinmap_problems`: every pin exists with the right direction and
  width, every input mapped or tied) and against the wrapper (`fits`: the same port kinds, a bit write mask for byte enables).
- **None fits** (more ports than any macro, a read latency other than 1, a clock no macro meets, `options.flops`): flip-flops, with why.
- **A large memory left as flip-flops is a question.** A wrapper of 4 KB or more (`macro.REVIEW_BYTES`) that ended up as flip-flops (not by
  `options.flops`) goes to a read-only LLM stage (`REVIEW`) with the code's notes (every family it rejected and why) and the kept pin maps.
  It judges each reason: `check_wrong` (a code check rejected a macro that is right), `mismatch` (true, but a change of the design would
  remove it) or `intended` (kept with the wrapper, no question, not judged again until the wrapper changes). The first two become a blocking
  `design_choice` question (`schemas/questions/asic_macro.*`, ids `MAC<n>`): **use `<macro>` anyway** (that family's pin check is overridden;
  the lock-step check still has to pass), **keep flip-flops**, **change the design** (the stage's request, or your own text, goes once to the
  spec step of the flow that owns the RTL). An answer is an input of the step: it runs again and applies it; answered questions stay as
  decisions (`asks` in the JSON).
- **The ASIC body** (`build/syn/asic/macros/<wrapper>.sv`, code): the wrapper file with the wrapper's header kept (parameters, ports) and
  its body replaced by the macros, the address split (low bits to the macros, high bits select the row), the byte enables expanded to the
  bit mask, padding for a word that is not a multiple of the macro width, and the read mux on the row registered with the access (latency 1).
  `src/rtl/` is never changed.
- **`.db`.** The macros' Liberty files are written as `.db` by Library Compiler (tool role `lib_compile`, `lc_shell -f`; the script by
  code); without the role the step fails and says so.
- **The check.** The body (renamed) and the behavioural wrapper in lock-step with the macro's Verilog model (tool roles `sim` + `run`):
  every test address written in full, then random reads and writes with random masks, the read data compared; `fail` fails the step, no
  simulator or model is `n/a`, never a pass.
- **Updates.** A wrapper whose text, ports, corner, PDK folder, clock and options did not change keeps its macro, body and check (no LLM,
  no tool); a changed text asks for its `MemSpec` again, a new macro family for its `PinMap` (kept in the JSON).

`asic_synth`, the quick estimate and `asic_lec` read the RTL with each mapped wrapper's file replaced by its body (`AsicStep.synth_files`),
the macros' `.db` in the link library only (`link_library`, never `target_library`: logic is not mapped onto them; Formality's `read_db`
of both containers) and the macro cells `dont_touch`. A change of the macros makes the synthesis stale (`asic_macro.json` is one of its
inputs). Not done yet: per-wrapper clocks (every wrapper is held to the fastest SDC clock), several wrappers in one file (give each its own),
read latencies other than 1, a choice of threshold voltage (equal areas go by name).

## Synthesis (`asic_synth`)

`options`: `library` (the `.db` of the standard cells; a list for several; `~` and `$ENV` expand), `compile` (default `compile_ultra`),
`max_paths`, `extra_tcl` (lines after `link`: `set_max_area`, `set_dont_use`, operating conditions, …), `defines`, and the targets
`min_slack_ns` (default 0) and `max_area_um2` (none). The default library is the GF180MCU 7-track 5 V cell library's typical corner
(`$PDK_ROOT/GF180/…/build/synopsys/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.db`; `PDK_ROOT` is where your PDKs are, docs/user_guide.md#setting-up-the-eda-tools-for-your-site); change it in **Settings** (`,` on the `asic_synth`
step: Library, Compile command, Min setup slack, Max area), through the assistant, or `pipeline.step_options.asic_synth.library` in q3tui.yaml. It is one choice for both flows, made by **technology, then corner** from the catalog `pdks.json` (only technologies whose `.db` files exist are offered). The built-in catalog (`q3tui/flows/asic/pdks.json`) lists **open-source PDKs only**: GF180MCU 7-track 5 V (180 nm) and FreePDK45 OSU gscl45nm (45 nm). Any other PDK goes in **your project's** `<project>/pdks.json` (same format; added to the built-in ones, an entry with the same `id` replaces one, `"only": true` hides the built-in ones) — never in the repo. The clock edit dialog of the SDC tab (either flow) has *ASIC technology* and *ASIC library corner* (the corners follow the technology; the typical corner is picked with it), and the FPGA flow's Settings has the same *ASIC library (.db)* as a path (an `asic_synth` tab) for a library that is not in the catalog (the dialog then shows the path). The choice is saved for both flows, and the **Estimate ASIC Fmax** button uses what the form shows. The Fmax hint names it ("GF180MCU 7-track 5 V · tt_025C_5v00").

The script sets the SVF first (Formality needs the guidance for what `compile` changes), analyzes / elaborates / links the RTL,
runs `extra_tcl`, sources `constraints/sdc/sdc.tcl`, compiles, writes the netlist (`change_names -rules verilog`), the `.ddc`, the SDC, and the
reports `area`, `timing` (the worst paths), `qor`, `power`, `constraints` (`-all_violators`), `check_design`, `check_timing`.
**The ASIC's own clock.** The flows share `constraints/sdc/sdc.json`, but each clock can have its own ASIC frequency: the *ASIC MHz* column of the SDC tab (`e` on the clock: *ASIC frequency*; empty / `same` = the FPGA's frequency), or `sdc_set key=clock.<name>.asic_freq_mhz value=250` (the assistant, `q3tui act`). It is a constraint, so it lives in `sdc.json` with the others, not in Settings. `asic_synth` renders the shared constraints with those clocks changed into `asic/sdc/` and Design Compiler sources that; `constraints/sdc/` (the FPGA's) is not touched. A change makes only the ASIC synthesis stale. `asic_synth.json` records `clock_override`.

**Quick estimate (`asic_estimate`).** The Fmax above needs the full synthesis (minutes). For the number next to the frequency you type, `asic_estimate` (`E` in the SDC tab, the **Estimate ASIC Fmax** button of a clock's edit dialog — the answer shows in the dialog, next to the *ASIC frequency* field you set — `q3tui act asic_estimate`, the assistant; registered in the FPGA flow too) runs Design Compiler at low effort (`compile -map_effort low`, about a minute) with only the clocks constrained at a probe period the library cannot meet — 1 ns, or the `probe_ns` of the technology in `pdks.json` (0.15 ns for a 14 nm library), because the tool's result at a moderate violation is erratic on a fast library: when the library meets the probe, the next run uses half of the period its worst path needed (up to three runs), and the best run of each clock counts (no I/O delays: they scale with the period): the worst register-to-register path then shows as a violation and the Fmax is `1000 / (probe − slack)`. It uses the library of `asic_synth` and writes `schemas/asic_estimate.json`, no netlist. Low effort maps a bit slower than `compile_ultra`, so it leans pessimistic (sample block, GF180: 240 MHz estimated in 59 s; the full run met 240 and estimated 254 from a missed 300; a 14 nm library, RVT tt: about 4.3 GHz in 85 s). The hint shows a fresh synthesis first, then a fresh estimate (`~` in the column, "quick estimate" in the note), then an older result marked with `*`.

**Expected frequency:** for each clock path group the report gives the Fmax the library allows with the worst setup path as it is: `1000 / (period − slack)` (`timing.fmax_mhz`, `timing.groups`; the QoR tab's *Expected Fmax* row, and the step's log line), so a clock set to 300 MHz in the SDC that the PDK cannot reach says "expected Fmax ≈ 254 MHz". It is an estimate from the current netlist (the I/O delays scale with the period, and a looser clock lets the tool trade area for speed), good for choosing the next clock target; synthesize again at that clock to confirm. The number is also shown where you set the frequency: the FPGA flow's SDC tab has an *ASIC Fmax MHz* column on the clocks (`≥`: the ASIC met the clock it was given and can go faster, `*`: the RTL changed since that run, `–`: the ASIC flow has not run), and the `sdc` step's log and `sdc_set` say "i_clk: ASIC ≈ 254 MHz (tt_025C_5v00)" (`lib/hints.py` reads `schemas/asic_synth.json`; it runs no tool).

`schemas/asic_synth.json` has the numbers and the verdict (`timing`, `area`, `constraints`, `overall`). There is no wire-load model or
placement: these are post-synthesis numbers, and power has no switching activity (the default estimate).

### Waivers

What the synthesis report flags can be waived, each with its reason, in `reviews/asic_synth_waivers.json` (yours: kept on reset;
`lib/waivers.py`): a constraint group of `report_constraint -all_violators` (`min_delay/hold`, `max_transition`, …; a timing group only up to
`max_ns` of violation — the TUI takes the group's worst violation now, so a worse one later is open again), one violation
(`<group>:<endpoint>`) or a warning code of check_design and the Design Compiler log (`LINT-28`, `VER-318`, …). A waived violation does
not fail the `constraints` verdict; a waived code no longer asks for a look. The step's **Waivers** tab lists every group and code with its
count, worst slack and state (`w` waive with a reason, `u` remove); the actions `asic_waive` / `asic_unwaive` do the same from the
assistant or `q3tui act`. The waiver file is an input of `asic_synth`; when the script, the RTL, the SDC and the libraries are those of the
last run (`dc_key` in the JSON), the step scores its reports again without running Design Compiler (a target or a waiver changed). Typical:
the hold violations at the macro pins before placement (a few 10 ps: no wire or clock-tree delay yet) — waived as fixed in physical design.

## Equivalence (`asic_lec`)

Formality reads the RTL as the reference and the netlist (with the library) as the implementation, sets the SVF, runs `match` and `verify`.
Equivalent → done. Not equivalent, inconclusive or no verdict is a failed step, never waived (the failing points are in
`build/syn/asic/reports/lec.rpt`). When Formality refuses to link the RTL on an interpretation message (for example `FMR_ELAB-147`, an index that
may leave an array), the step names the message: fix the RTL, or accept it with `options.message_filter: [FMR_ELAB-147]`.

## Tools

Template roles (`q3tui/eda/presets/flows/asic.json`, copied into the project's `config/tools.json` by `q3tui tools init`): `asic_synth` = `dc_shell -f {script}` with
module `synopsys/syn` (log parser `dc`), `asic_lec` = `fm_shell -f {script}` with module `synopsys/formality`, `lib_compile` = `lc_shell -f {script}`
with module `synopsys/libraryCompiler` (the memory macros' `.lib` → `.db`). `mem_compile` (a memory compiler) has no template: `asic_macro`
records the command its stage proposes for it. The check of `asic_macro` uses the simulation roles `sim` + `run`.
Define your own `asic_synth` / `asic_lec` roles in `config/tools.json` / `tools.roles` for other versions or tools.

## Not built yet

GCA and its waivers (the Sanity lane of the flow map), the convergence gate, handing timing failures back to the spec, other synthesis
tools (Genus, Yosys), multiple corners.

## Where the code is

All of it under `q3tui/flows/asic/`: `FLOW.md`, one folder per step (`step.py`, `md/skill.md`), `lib/` (port rules, Design Compiler script and
report readers, Formality script and reader, `macro.py`: the memory macros), `addon.py` (settings, `asic_handoff`, the SDC actions), `panels.py` (TUI). The SDC
step, its actions and its editor are the FPGA flow's. Core has only the flow-map box.
