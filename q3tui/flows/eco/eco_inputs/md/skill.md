---
label: "1"
title: ECO inputs (ORG RTL, ORG netlist, requirement)
deps: []
gate: none
options:
  library: null       # the .db (or a list); null: the one the asic flow synthesized the ORG netlist with (schemas/asic_synth.json)
  rtl: null           # the ORG RTL filelist; null (all three): the step asks you — the defaults or your own paths
  netlist: null       # the ORG netlist (.v); the .sdc beside it is the STA's constraints
  requirement: null   # what the ECO must change (markdown)
  top: null           # null: schemas/structured_spec.json metadata.top_module
  ref_name: null      # the ref/ folder name of the ORG design; null: the step asks you (default: the top module)
view: [schemas/eco_inputs.json, eco/ref.json, eco/requirement.md]
---
Chooses the ECO's inputs. With `rtl` / `netlist` / `requirement` unset the step asks once: the defaults (the asic flow's `src/rtl/filelist.f`, `build/syn/asic/netlist/<top>.v`, and `eco/requirement.md`) or your own paths (`rtl=… netlist=… requirement=…`). The ORG design is kept in `ref/<name>/` (you are asked the name; `ref/<name>_DDMMYYYY_HHMMSS` when that folder exists): with the project's own RTL (`src/rtl`: **project** mode) its `spec/`, `src/`, `constraints/`, `schemas/`, else (**external** mode, a fire-fighting ECO) the RTL files; in both the ORG netlist with its `.sdc` / `.svf` (`netlist/`). `eco/ref.json` points to it; no reset deletes it or `ref/` (a new ECO: delete `eco/ref.json`). `library` (the `.db` of the standard cells) is the whole flow's: Design Compiler, Formality and PrimeTime read it.
