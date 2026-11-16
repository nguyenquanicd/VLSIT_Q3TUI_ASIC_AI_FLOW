---
name: asic
title: ASIC synthesis — SDC → ASIC port check → memory macros → Design Compiler → logic equivalence check
version: 1
session: fresh
tools:
- asic_synth
- asic_lec
- lib_compile
steps:
- sdc
- asic_port
- asic_macro
- asic_synth
- asic_lec
---
ASIC synthesis of the RTL the VLSIT flow produced (`src/rtl/`, read only) with a standard-cell library: `sdc` renders the constraints (first: the clock decides which memory macros are fast enough), `asic_port` finds what an ASIC cannot take (FPGA primitives and attributes, memories that need macros, simulation-only code), `asic_macro` maps the memory wrappers to the PDK's memory macros (a memory compiler, else a tiling of pre-generated macros; the ASIC bodies replace the behavioural wrappers in the synthesis), `asic_synth` runs Design Compiler (netlist + area / timing / power), `asic_lec` proves the netlist equals the RTL (Formality). The library is a setting (`asic_synth` tab of Settings, or `options.library`).
