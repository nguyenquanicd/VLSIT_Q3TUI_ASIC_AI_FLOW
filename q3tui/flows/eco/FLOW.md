---
name: eco
title: ECO — requirement + ORG design (ref/) → spec / RTL(F) modified → dv + Sanity → netlist patch → EQ → STA
version: 1
session: fresh
tools:
- asic_synth
- asic_lec
- eco_sta
steps:
- eco_inputs
- eco_eq1
- eco_spec
- eco_rtl
- eco_verify
- eco_patch
- eco_apply
- eco_eq2
- eco_sta
---
An engineering change order on a block that is already synthesized, independent of the other flows: its entry is a modification requirement, and the spec / RTL are modified, not generated. `eco_inputs` takes the ORG RTL (a filelist), the ORG netlist and the requirement (the asic flow's outputs, or paths you give) and keeps the ORG design in `ref/<name>/` (you name it; `ref/<name>_DDMMYYYY_HHMMSS` when taken): the later steps take their ORG artifacts from there. Two modes, from where the RTL is: **project** (this project's `src/rtl`, made by the VLSI flows) — `eco_spec` updates the spec documents in place, `eco_rtl` modifies `src/rtl` in place, `eco_verify` asks whether dv and Sanity run again and, if so, needs both to pass before the netlist ECO (their RTL fixes come back to `eco_rtl`, the smallest change); **external** (a filelist from elsewhere: a fire-fighting ECO) — no spec update, RTL(F) is a copy in `eco/rtl/`, no dv / Sanity. `eco_eq1` proves the ORG netlist equal to the ORG RTL (Formality; a passed `asic_lec` is offered instead), `eco_patch` writes the Design Compiler netlist edits that make the RTL change in the ORG netlist (LLM, guarded), `eco_apply` runs them on the ORG netlist (Design Compiler, no compile) to the ECO NETLIST, `eco_eq2` proves the ECO NETLIST equal to RTL(F) (Formality), `eco_sta` checks its timing (PrimeTime); a setup violation gets a timing fix, applied and checked again (bounded). RTL(F) changes as little as it can against the ORG RTL.
