---
label: "6"
title: PATCH CMD — netlist edits for the RTL change (AI)
deps: [eco_verify]
gate: human
options: {max_new_cells: 10}
view: [eco/patch/eco_patch.tcl, schemas/eco_patch.json, eco/rtl.diff]
---
The RTL change becomes Design Compiler netlist edits on the ORG netlist (`eco/patch/eco_patch.tcl`). Only netlist edits and queries are accepted (`create_cell`, `remove_cell`, `create_net`, `remove_net`, `connect_net`, `disconnect_net`, `create_port`, `size_cell`, `change_link`, `insert_buffer`, …; no loops, procs, files or shell): the file runs in dc_shell. The gate is your review of the patch. Tasks: **edits** (AI, read-only) writes the netlist edits; **check** refuses what is not a netlist edit or does not fit the netlist (one round back to the AI); **cost** measures the patch in the netlist (new cells, nets, connections: `schemas/eco_patch.json`): when it adds more than `max_new_cells` cells, you are asked whether to keep it or have eco_rtl look for an RTL change with a smaller netlist impact (keeping it is recommended; auto-answer keeps it).
