---
label: "6"
title: PATCH CMD — netlist edits for the RTL change (AI)
deps: [eco_verify]
gate: human
options: {}
view: [eco/patch/eco_patch.tcl, schemas/eco_patch.json, eco/rtl.diff]
---
The RTL change becomes Design Compiler netlist edits on the ORG netlist (`eco/patch/eco_patch.tcl`). Only netlist edits and queries are accepted (`create_cell`, `remove_cell`, `create_net`, `remove_net`, `connect_net`, `disconnect_net`, `create_port`, `size_cell`, `change_link`, `insert_buffer`, …; no loops, procs, files or shell): the file runs in dc_shell. The gate is your review of the patch.
