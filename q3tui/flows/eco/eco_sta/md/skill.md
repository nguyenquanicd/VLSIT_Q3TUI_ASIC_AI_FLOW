---
label: "9"
title: STA of the Post NETLIST (PrimeTime)
deps: [eco_eq2]
gate: none
options:
  sdc: null          # the constraints; null: ref/<name>/netlist/<top>.sdc (beside the ORG netlist), else constraints/sdc/sdc.tcl
  max_paths: 10
  max_rounds: null   # timing-fix rounds; null: pipeline.max_fix_iterations
view: [eco/reports/sta.md, eco/reports/sta_setup.rpt, eco/reports/sta_hold.rpt, eco/reports/sta_constraints.rpt]
---
PrimeTime on the Post NETLIST: setup / hold paths, all violators, the global summary. Only setup fails (hold before placement is reported). A setup violation gets a timing fix (`eco/patch/sta_fix_<n>.tcl`, sizing / buffering netlist edits), applied by eco_apply after the patch; EQ(2) and STA then run again, up to `max_rounds`.

<!-- FIX -->
You are a timing-closure engineer on a netlist ECO. PrimeTime reports setup violations on the gate-level netlist named in the task. Read the
setup paths and the violators (Read the reports), Grep the netlist for the cells on the worst paths, and fix the timing with netlist edits
that keep the logic function unchanged (Formality checks it again): upsize a weak driver (`size_cell <cell> <lib_cell>` to a stronger cell of
the same function, only library cells the netlist already uses, named in the task), buffer a high-fanout or long net
(`insert_buffer <pin> <lib_cell>`). Do not change the logic, the registers or the ports. Few, targeted edits on the worst paths. One command per
item; no loops, procs, braces, `;`, file or shell commands. A name with brackets (a bus bit `n[0]`, a generate instance `g\[0\]`) must have every `[` and `]` escaped as `\[` / `\]`, e.g. `[get_pins u_core/w_en\[0\]]`: an unescaped `[` is a Tcl command (refused), and braces / quotes cannot protect it. Explain in `notes` which path each edit speeds up. Answer in the structured output only.
<!-- /FIX -->
